/** @file Route guard that redirects signed-out visitors to the login page. */

import { Alert, Box, Button } from '@mui/material'
import { Navigate, Outlet } from 'react-router-dom'

import { useAuthStore } from '../store/auth'

/**
 * Explain that the session check failed and offer to run it again.
 *
 * Shown instead of a redirect when `/me` failed for a reason other than a 401,
 * such as a network error or a backend restart, because that failure does not
 * prove the visitor is signed out.
 *
 * @returns The alert with its Retry button.
 */
function SessionCheckFailed() {
    const fetchMe = useAuthStore((s) => s.fetchMe)

    return (
        <Box sx={{ p: 4 }}>
            <Alert
                severity="error"
                action={
                    <Button color="inherit" size="small" onClick={() => void fetchMe()}>
                        Retry
                    </Button>
                }
            >
                Could not reach the server to check your session.
            </Alert>
        </Box>
    )
}

/**
 * Render the nested routes only when a user is signed in.
 *
 * Renders nothing while the initial `fetchMe` is still in flight, so a
 * signed-in visitor reloading the page is not bounced to the login page
 * before the session is confirmed. When that check failed without a 401, a
 * retry alert replaces the redirect. The redirect replaces the history entry,
 * so the back button does not loop between the guarded route and login.
 *
 * @returns Nothing while loading, the matched child route for a signed-in
 *   user, the retry alert after a failed session check, or a redirect to
 *   `/login`.
 */
export default function ProtectedRoute() {
    const user = useAuthStore((s) => s.user)
    const isLoading = useAuthStore((s) => s.isLoading)
    const sessionCheckFailed = useAuthStore((s) => s.sessionCheckFailed)

    if (isLoading) return null
    if (user) return <Outlet />
    if (sessionCheckFailed) return <SessionCheckFailed />
    return <Navigate to="/login" replace />
}
