/** @file Route guard that redirects signed-out visitors to the login page. */

import { Navigate, Outlet } from 'react-router-dom'

import { useAuthStore } from '../store/auth'

/**
 * Render the nested routes only when a user is signed in.
 *
 * Renders nothing while the initial `fetchMe` is still in flight, so a
 * signed-in visitor reloading the page is not bounced to the login page
 * before the session is confirmed. The redirect replaces the history entry,
 * so the back button does not loop between the guarded route and login.
 *
 * @returns Nothing while loading, a redirect to `/login` when signed out, or
 *   the matched child route.
 */
export default function ProtectedRoute() {
    const user = useAuthStore((s) => s.user)
    const isLoading = useAuthStore((s) => s.isLoading)

    if (isLoading) return null
    if (!user) return <Navigate to="/login" replace />
    return <Outlet />
}
