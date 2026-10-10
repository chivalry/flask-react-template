/** @file Route table for the application. */

import { useEffect } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'

import AppShell from './components/layout/AppShell'
import ProtectedRoute from './components/ProtectedRoute'
import Home from './pages/Home'
import Login from './pages/Login'
import Register from './pages/Register'
import { useAuthStore } from './store/auth'

/**
 * Declare every route and the guards around them.
 *
 * On mount the store asks the server who is signed in, so a reload restores
 * the session from the cookie. Everything except the auth pages sits behind
 * {@link ProtectedRoute} inside the {@link AppShell}, and unknown paths
 * redirect to the home page rather than showing a 404.
 *
 * @returns The route table.
 */
export default function App() {
    const fetchMe = useAuthStore((s) => s.fetchMe)

    useEffect(() => {
        void fetchMe()
    }, [fetchMe])

    return (
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
    )
}
