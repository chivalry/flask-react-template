/** @file Route guard that keeps non-admins out of the admin section. */

import { Navigate, Outlet } from 'react-router-dom'

import { useAuthStore } from '../store/auth'
import { isAdmin } from '../types/auth'

/**
 * Render the nested routes only for an admin; everyone else lands on the home page.
 *
 * Sits inside {@link ProtectedRoute}, so a user is always present here.
 *
 * @returns The matched child route for an admin, otherwise a redirect.
 */
export default function AdminRoute() {
    const user = useAuthStore((s) => s.user)

    if (user && isAdmin(user.role)) return <Outlet />
    return <Navigate to="/" replace />
}
