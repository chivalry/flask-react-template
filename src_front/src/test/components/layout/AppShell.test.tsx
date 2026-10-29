import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { AxiosResponse } from 'axios'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { logout } from '../../../api/auth'
import AppShell from '../../../components/layout/AppShell'
import { useAuthStore } from '../../../store/auth'
import { adminUser, plainUser } from '../../utils/fixtures'

vi.mock('../../../api/auth')

const renderShell = (initialPath = '/') =>
    render(
        <MemoryRouter initialEntries={[initialPath]}>
            <Routes>
                <Route path="/login" element={<div>Login page</div>} />
                <Route element={<AppShell />}>
                    <Route index element={<div>Outlet child content</div>} />
                    <Route path="/other" element={<div>Other page</div>} />
                    <Route path="/admin/users" element={<div>Users page</div>} />
                </Route>
            </Routes>
        </MemoryRouter>,
    )

// Sign the admin in, log out from the shell, and check that the session ends on the
// login page; each logout test sets up the request's outcome first.
const logOutAndExpectLoginPage = async () => {
    const user = userEvent.setup()
    useAuthStore.getState().setUser(adminUser)
    renderShell()

    await user.click(screen.getByRole('button', { name: 'Logout' }))

    expect(await screen.findByText('Login page')).toBeInTheDocument()
    expect(logout).toHaveBeenCalledTimes(1)
    expect(useAuthStore.getState().user).toBeNull()
}

describe('AppShell', () => {
    beforeEach(() => {
        vi.clearAllMocks()
        useAuthStore.setState({ user: null, isLoading: false })
    })

    it('renders the application title in the app bar', () => {
        renderShell()

        expect(
            within(screen.getByRole('banner')).getByText('Flask React Template'),
        ).toBeInTheDocument()
    })

    it('renders the Home navigation link, marked current on the home route', () => {
        renderShell()

        const homeLink = screen.getByRole('link', { name: 'Home' })
        expect(homeLink).toHaveAttribute('href', '/')
        expect(homeLink).toHaveAttribute('aria-current', 'page')
    })

    it('does not mark Home as current on another route', () => {
        renderShell('/other')

        expect(screen.getByText('Other page')).toBeInTheDocument()
        expect(screen.getByRole('link', { name: 'Home' })).not.toHaveAttribute(
            'aria-current',
        )
    })

    it('shows the Admin link to an admin', () => {
        useAuthStore.getState().setUser(adminUser)

        renderShell()

        expect(screen.getByRole('link', { name: 'Admin' })).toHaveAttribute(
            'href',
            '/admin',
        )
    })

    it('hides the Admin link from a user who is not an admin', () => {
        useAuthStore.getState().setUser(plainUser)

        renderShell()

        expect(screen.getByRole('link', { name: 'Home' })).toBeInTheDocument()
        expect(screen.queryByRole('link', { name: 'Admin' })).not.toBeInTheDocument()
    })

    it('marks Admin current and not Home on a page below /admin', () => {
        useAuthStore.getState().setUser(adminUser)

        renderShell('/admin/users')

        expect(screen.getByText('Users page')).toBeInTheDocument()
        expect(screen.getByRole('link', { name: 'Admin' })).toHaveAttribute(
            'aria-current',
            'page',
        )
        expect(screen.getByRole('link', { name: 'Home' })).not.toHaveAttribute(
            'aria-current',
        )
    })

    it('keeps every button named when its label is hidden', () => {
        useAuthStore.getState().setUser(adminUser)
        renderShell()

        // Below sm a media query hides the labels; jsdom ignores it, so hide them here.
        for (const label of ['Home', 'Admin', 'Logout']) {
            screen.getByText(label).style.display = 'none'
        }

        expect(screen.getByRole('link', { name: 'Home' })).toBeInTheDocument()
        expect(screen.getByRole('link', { name: 'Admin' })).toBeInTheDocument()
        expect(screen.getByRole('button', { name: 'Logout' })).toBeInTheDocument()
    })

    it('renders the signed-in user email', () => {
        useAuthStore.getState().setUser(adminUser)

        renderShell()

        expect(screen.getByText(adminUser.email)).toBeInTheDocument()
    })

    it('renders no email when nobody is signed in', () => {
        renderShell()

        expect(screen.queryByText(adminUser.email)).not.toBeInTheDocument()
        expect(screen.getByRole('button', { name: 'Logout' })).toBeInTheDocument()
    })

    it('calls logout, clears the user, and navigates to /login on success', async () => {
        vi.mocked(logout).mockResolvedValue({
            data: { message: 'Logged out' },
        } as AxiosResponse<{ message: string }>)

        await logOutAndExpectLoginPage()
    })

    it('still clears the user and navigates to /login when logout fails', async () => {
        vi.mocked(logout).mockRejectedValue(new Error('logout request failed'))

        await logOutAndExpectLoginPage()
    })

    it('renders route children through the Outlet inside the main region', () => {
        renderShell()

        expect(
            within(screen.getByRole('main')).getByText('Outlet child content'),
        ).toBeInTheDocument()
    })

    it('fills the visible viewport with a flex-column main that can shrink', () => {
        renderShell()

        const main = screen.getByRole('main')

        // The shell is a flex column as tall as the viewport, and main takes the rest.
        expect(main.parentElement).toHaveStyle({
            display: 'flex',
            flexDirection: 'column',
            height: '100dvh',
        })
        expect(main).toHaveStyle({
            display: 'flex',
            flexDirection: 'column',
            flexGrow: '1',
            minHeight: '0px',
        })
    })
})
