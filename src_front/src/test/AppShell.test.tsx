import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { AxiosResponse } from 'axios'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { logout } from '../api/auth'
import AppShell from '../components/layout/AppShell'
import { useAuthStore } from '../store/auth'
import type { AuthUser } from '../types/auth'

vi.mock('../api/auth')

type UnhandledRejectionListener = (reason: unknown, promise: Promise<unknown>) => void

interface UnhandledRejectionEmitter {
    listeners(eventName: 'unhandledRejection'): UnhandledRejectionListener[]
    on(eventName: 'unhandledRejection', listener: UnhandledRejectionListener): void
    removeAllListeners(eventName: 'unhandledRejection'): void
}

const rejectionEmitter = (globalThis as unknown as { process: UnhandledRejectionEmitter })
    .process

// handleLogout intentionally re-raises a logout API failure after its finally block
// runs, and React discards the click handler's promise, so the rejection can only
// surface as a process-level unhandled rejection. Swallow it for the wrapped action.
const suppressUnhandledRejections = async (action: () => Promise<void>) => {
    const originalListeners = rejectionEmitter.listeners('unhandledRejection')
    rejectionEmitter.removeAllListeners('unhandledRejection')
    rejectionEmitter.on('unhandledRejection', () => undefined)
    try {
        await action()
        await new Promise((resolve) => setTimeout(resolve, 0))
    } finally {
        rejectionEmitter.removeAllListeners('unhandledRejection')
        for (const listener of originalListeners) {
            rejectionEmitter.on('unhandledRejection', listener)
        }
    }
}

const testUser: AuthUser = {
    id: 1,
    uuid: 'user-uuid-1',
    email: 'tester@example.com',
    role: 'admin',
    created_at: '2026-08-01T00:00:00Z',
    updated_at: '2026-08-01T00:00:00Z',
}

const renderShell = (initialPath = '/') =>
    render(
        <MemoryRouter initialEntries={[initialPath]}>
            <Routes>
                <Route path="/login" element={<div>Login page</div>} />
                <Route element={<AppShell />}>
                    <Route index element={<div>Outlet child content</div>} />
                    <Route path="/other" element={<div>Other page</div>} />
                </Route>
            </Routes>
        </MemoryRouter>,
    )

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

    it('renders the signed-in user email', () => {
        useAuthStore.getState().setUser(testUser)

        renderShell()

        expect(screen.getByText('tester@example.com')).toBeInTheDocument()
    })

    it('renders no email when nobody is signed in', () => {
        renderShell()

        expect(screen.queryByText('tester@example.com')).not.toBeInTheDocument()
        expect(screen.getByRole('button', { name: 'Logout' })).toBeInTheDocument()
    })

    it('calls logout, clears the user, and navigates to /login on success', async () => {
        const user = userEvent.setup()
        useAuthStore.getState().setUser(testUser)
        vi.mocked(logout).mockResolvedValue({
            data: { message: 'Logged out' },
        } as AxiosResponse<{ message: string }>)
        renderShell()

        await user.click(screen.getByRole('button', { name: 'Logout' }))

        expect(await screen.findByText('Login page')).toBeInTheDocument()
        expect(logout).toHaveBeenCalledTimes(1)
        expect(useAuthStore.getState().user).toBeNull()
    })

    it('still clears the user and navigates to /login when logout fails', async () => {
        const user = userEvent.setup()
        useAuthStore.getState().setUser(testUser)
        vi.mocked(logout).mockRejectedValue(new Error('logout request failed'))
        renderShell()

        await suppressUnhandledRejections(async () => {
            await user.click(screen.getByRole('button', { name: 'Logout' }))
            expect(await screen.findByText('Login page')).toBeInTheDocument()
        })

        expect(logout).toHaveBeenCalledTimes(1)
        expect(useAuthStore.getState().user).toBeNull()
    })

    it('renders route children through the Outlet inside the main region', () => {
        renderShell()

        expect(
            within(screen.getByRole('main')).getByText('Outlet child content'),
        ).toBeInTheDocument()
    })
})
