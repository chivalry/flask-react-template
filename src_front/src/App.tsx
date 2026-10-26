/** @file Route table for the application. */

import { lazy, Suspense, useEffect } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'

import AdminRoute from './components/AdminRoute'
import AppShell from './components/layout/AppShell'
import ProtectedRoute from './components/ProtectedRoute'
import RouteErrorBoundary from './components/RouteErrorBoundary'
import { useSessionQueryCache } from './hooks/useSessionQueryCache'
import { useAuthStore } from './store/auth'

const AdminPage = lazy(() => import('./pages/AdminPage'))
const Home = lazy(() => import('./pages/Home'))
const Login = lazy(() => import('./pages/Login'))
const Register = lazy(() => import('./pages/Register'))

/**
 * Declare every route and the guards around them.
 *
 * Cached server state is cleared whenever the signed-in account changes, and on
 * mount the store asks the server who is signed in, so a reload restores the session
 * from the cookie. Everything except the auth pages sits behind
 * {@link ProtectedRoute} inside the {@link AppShell}; the admin section under
 * `/admin` adds {@link AdminRoute}, which sends everyone but an admin to the home
 * page. Unknown paths redirect to the home page rather than showing a 404. Each page
 * loads on first visit from its own chunk; until it arrives the boundary renders
 * nothing, as {@link ProtectedRoute} does during the session check. A
 * {@link RouteErrorBoundary} around the auth pages and another inside the shell
 * replace a page that throws, or whose chunk fails to load, with a fallback; inside
 * the shell the app bar stays on screen, and navigating to another page clears it.
 *
 * @returns The route table.
 */
export default function App() {
    useSessionQueryCache()
    const fetchMe = useAuthStore((s) => s.fetchMe)

    useEffect(() => {
        void fetchMe()
    }, [fetchMe])

    return (
        <Suspense fallback={null}>
            <Routes>
                <Route element={<RouteErrorBoundary />}>
                    <Route path="/login" element={<Login />} />
                    <Route path="/register" element={<Register />} />
                </Route>
                <Route element={<ProtectedRoute />}>
                    <Route element={<AppShell />}>
                        <Route element={<RouteErrorBoundary />}>
                            <Route index element={<Home />} />
                            <Route element={<AdminRoute />}>
                                <Route path="/admin/*" element={<AdminPage />} />
                            </Route>
                        </Route>
                    </Route>
                </Route>
                <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
        </Suspense>
    )
}
