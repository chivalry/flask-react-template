/** @file Route table for the application. */

import { lazy, Suspense, useEffect } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'

import AppShell from './components/layout/AppShell'
import ProtectedRoute from './components/ProtectedRoute'
import { useAuthStore } from './store/auth'

const Home = lazy(() => import('./pages/Home'))
const Login = lazy(() => import('./pages/Login'))
const Register = lazy(() => import('./pages/Register'))

/**
 * Declare every route and the guards around them.
 *
 * On mount the store asks the server who is signed in, so a reload restores
 * the session from the cookie. Everything except the auth pages sits behind
 * {@link ProtectedRoute} inside the {@link AppShell}, and unknown paths
 * redirect to the home page rather than showing a 404. Each page loads on
 * first visit from its own chunk; until it arrives the boundary renders
 * nothing, as {@link ProtectedRoute} does during the session check.
 *
 * @returns The route table.
 */
export default function App() {
    const fetchMe = useAuthStore((s) => s.fetchMe)

    useEffect(() => {
        void fetchMe()
    }, [fetchMe])

    return (
        <Suspense fallback={null}>
            <Routes>
                <Route path="/login" element={<Login />} />
                <Route path="/register" element={<Register />} />
                <Route element={<ProtectedRoute />}>
                    <Route element={<AppShell />}>
                        <Route index element={<Home />} />
                    </Route>
                </Route>
                <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
        </Suspense>
    )
}
