/** @file App shell: top navigation bar around the routed page content. */

import { AppBar, Box, Button, Toolbar, Typography } from '@mui/material'
import LogoutIcon from '@mui/icons-material/Logout'
import { Suspense } from 'react'
import { Link, Outlet, useLocation, useNavigate } from 'react-router-dom'

import { useAuthStore } from '../../store/auth'

/** One entry in the top navigation bar. */
interface NavLinkItem {
    to: string
    label: string
}

/** Every page reachable from the navigation bar, in display order. */
const NAV_LINKS: NavLinkItem[] = [{ to: '/', label: 'Home' }]

/**
 * Render the navigation links, marking the one for the current route.
 *
 * @returns The nav button elements.
 */
function NavLinks() {
    const { pathname } = useLocation()
    return (
        <>
            {NAV_LINKS.map(({ to, label }) => (
                <Button
                    key={to}
                    color="inherit"
                    component={Link}
                    to={to}
                    aria-current={pathname === to ? 'page' : undefined}
                >
                    {label}
                </Button>
            ))}
        </>
    )
}

/**
 * Render the signed-in user's email and the Logout button.
 *
 * @returns The user menu elements.
 */
function UserMenu() {
    const user = useAuthStore((s) => s.user)
    const logout = useAuthStore((s) => s.logout)
    const navigate = useNavigate()

    /**
     * Sign out, then return to the login page.
     *
     * The store's `logout` never rejects: it clears the local user whether or
     * not the request succeeded, so this handler only has to navigate.
     */
    const handleLogout = async () => {
        await logout()
        navigate('/login')
    }

    return (
        <>
            {user ? <Typography variant="body2">{user.email}</Typography> : null}
            <Button color="inherit" startIcon={<LogoutIcon />} onClick={handleLogout}>
                Logout
            </Button>
        </>
    )
}

/**
 * Render the navigation bar and an outlet for the active route.
 *
 * The outlet has its own Suspense boundary, so the bar stays on screen while
 * a page's chunk loads.
 *
 * @returns The application shell.
 */
export default function AppShell() {
    return (
        <Box sx={{ display: 'flex', flexDirection: 'column', minHeight: '100vh' }}>
            <AppBar position="static">
                <Toolbar sx={{ gap: 2 }}>
                    <Typography variant="h6" component="div" sx={{ mr: 2 }}>
                        Flask React Template
                    </Typography>
                    <NavLinks />
                    <Box sx={{ flexGrow: 1 }} />
                    <UserMenu />
                </Toolbar>
            </AppBar>
            <Box component="main" sx={{ flex: 1, minHeight: 0 }}>
                <Suspense fallback={null}>
                    <Outlet />
                </Suspense>
            </Box>
        </Box>
    )
}
