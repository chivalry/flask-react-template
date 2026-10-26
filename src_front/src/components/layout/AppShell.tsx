/** @file App shell: top navigation bar around the routed page content. */

import AdminPanelSettingsIcon from '@mui/icons-material/AdminPanelSettings'
import HomeIcon from '@mui/icons-material/Home'
import LogoutIcon from '@mui/icons-material/Logout'
import { AppBar, Box, Button, Toolbar, Typography } from '@mui/material'
import type { SxProps, Theme } from '@mui/material'
import { Suspense } from 'react'
import type { ReactNode } from 'react'
import { Link, Outlet, useLocation, useNavigate } from 'react-router-dom'

import { useAuthStore } from '../../store/auth'
import { isAdmin } from '../../types/auth'

/** One entry in the top navigation bar. */
interface NavLinkItem {
    to: string
    label: string
    icon: ReactNode
    adminOnly?: boolean
}

/** Every page reachable from the navigation bar, in display order. */
const NAV_LINKS: NavLinkItem[] = [
    { to: '/', label: 'Home', icon: <HomeIcon /> },
    {
        to: '/admin',
        label: 'Admin',
        icon: <AdminPanelSettingsIcon />,
        adminOnly: true,
    },
]

/** Shrink a labeled top-bar button to its icon below the `sm` breakpoint. */
const COLLAPSIBLE_BUTTON_SX: SxProps<Theme> = {
    minWidth: { xs: 44, sm: 64 },
    '& .MuiButton-startIcon': { mr: { xs: 0, sm: 1 }, ml: { xs: 0, sm: -0.5 } },
}

/** Hide a top-bar button's label below the `sm` breakpoint. */
const COLLAPSIBLE_LABEL_SX: SxProps<Theme> = { display: { xs: 'none', sm: 'inline' } }

/**
 * Render the navigation links the signed-in user may see, marking the current one.
 *
 * A link is current on its own path or below it, so Home is current only on `/`.
 *
 * @returns The nav button elements.
 */
function NavLinks() {
    const { pathname } = useLocation()
    const user = useAuthStore((s) => s.user)
    const canSeeAdmin = user !== null && isAdmin(user.role)
    return (
        <>
            {NAV_LINKS.filter((link) => !link.adminOnly || canSeeAdmin).map(
                ({ to, label, icon }) => (
                    <Button
                        key={to}
                        color="inherit"
                        component={Link}
                        to={to}
                        aria-label={label}
                        aria-current={
                            pathname === to || pathname.startsWith(`${to}/`)
                                ? 'page'
                                : undefined
                        }
                        startIcon={icon}
                        sx={COLLAPSIBLE_BUTTON_SX}
                    >
                        <Box component="span" sx={COLLAPSIBLE_LABEL_SX}>
                            {label}
                        </Box>
                    </Button>
                ),
            )}
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
            {user ? (
                <Typography variant="body2" sx={{ display: { xs: 'none', sm: 'block' } }}>
                    {user.email}
                </Typography>
            ) : null}
            <Button
                color="inherit"
                aria-label="Logout"
                startIcon={<LogoutIcon />}
                onClick={handleLogout}
                sx={COLLAPSIBLE_BUTTON_SX}
            >
                <Box component="span" sx={COLLAPSIBLE_LABEL_SX}>
                    Logout
                </Box>
            </Button>
        </>
    )
}

/**
 * Render the navigation bar and an outlet for the active route.
 *
 * Below the `sm` breakpoint the bar tightens its spacing, the buttons shrink to
 * their icons, and the email hides, so it fits a phone-width screen. The outlet
 * has its own Suspense boundary, so the bar stays on screen while a page's chunk
 * loads.
 *
 * @returns The application shell.
 */
export default function AppShell() {
    return (
        <Box sx={{ display: 'flex', flexDirection: 'column', minHeight: '100vh' }}>
            <AppBar position="static">
                <Toolbar sx={{ gap: { xs: 0.5, sm: 2 } }}>
                    <Typography
                        variant="h6"
                        component="div"
                        sx={{ mr: { xs: 0.5, sm: 2 } }}
                    >
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
