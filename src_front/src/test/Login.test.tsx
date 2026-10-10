import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { AxiosResponse } from 'axios'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { login, me } from '../api/auth'
import Login from '../pages/Login'
import { useAuthStore } from '../store/auth'
import type { AuthUser } from '../types/auth'

vi.mock('../api/auth')

const testUser: AuthUser = {
    id: 1,
    uuid: 'user-uuid-1',
    email: 'tester@example.com',
    role: 'admin',
    created_at: '2026-08-01T00:00:00Z',
    updated_at: '2026-08-01T00:00:00Z',
}

const renderLogin = () =>
    render(
        <MemoryRouter initialEntries={['/login']}>
            <Routes>
                <Route path="/login" element={<Login />} />
                <Route path="/" element={<div>Home page</div>} />
            </Routes>
        </MemoryRouter>,
    )

const signInWith = async (
    user: ReturnType<typeof userEvent.setup>,
    email: string,
    password: string,
) => {
    await user.type(screen.getByLabelText('Email'), email)
    await user.type(screen.getByLabelText('Password'), password)
    await user.click(screen.getByRole('button', { name: 'Sign in' }))
}

describe('Login', () => {
    beforeEach(() => {
        vi.clearAllMocks()
        useAuthStore.setState({ user: null, isLoading: false })
    })

    it('shows the invalid email message and does not call the API', async () => {
        const user = userEvent.setup()
        renderLogin()

        await signInWith(user, 'not-an-email', 'password123')

        expect(await screen.findByText('Enter a valid email.')).toBeInTheDocument()
        expect(login).not.toHaveBeenCalled()
    })

    it('shows the required password message and does not call the API', async () => {
        const user = userEvent.setup()
        renderLogin()

        await user.type(screen.getByLabelText('Email'), 'user@example.com')
        await user.click(screen.getByRole('button', { name: 'Sign in' }))

        expect(await screen.findByText('Password is required.')).toBeInTheDocument()
        expect(login).not.toHaveBeenCalled()
    })

    it('signs in, loads the user, and navigates to / on success', async () => {
        const user = userEvent.setup()
        vi.mocked(login).mockResolvedValue({ data: testUser } as AxiosResponse<AuthUser>)
        vi.mocked(me).mockResolvedValue({ data: testUser } as AxiosResponse<AuthUser>)
        renderLogin()

        await signInWith(user, 'user@example.com', 'password123')

        expect(await screen.findByText('Home page')).toBeInTheDocument()
        expect(login).toHaveBeenCalledWith('user@example.com', 'password123')
        expect(me).toHaveBeenCalledTimes(1)
        expect(useAuthStore.getState().user).toEqual(testUser)
    })

    it('shows the server-provided message when the login request fails', async () => {
        const user = userEvent.setup()
        // The client's interceptor has already copied the backend's `{ error }`
        // text into the rejection's message by the time the page sees it.
        vi.mocked(login).mockRejectedValue(new Error('Invalid email or password.'))
        renderLogin()

        await signInWith(user, 'user@example.com', 'wrong-password')

        expect(await screen.findByRole('alert')).toHaveTextContent(
            'Invalid email or password.',
        )
        expect(me).not.toHaveBeenCalled()
        expect(useAuthStore.getState().user).toBeNull()
    })

    it('shows the fallback message when the failure is not an Error', async () => {
        const user = userEvent.setup()
        vi.mocked(login).mockRejectedValue({ response: { status: 500 } })
        renderLogin()

        await signInWith(user, 'user@example.com', 'password123')

        expect(await screen.findByRole('alert')).toHaveTextContent('Login failed.')
        expect(useAuthStore.getState().user).toBeNull()
    })

    it('shows the pending label and disables the button while signing in', async () => {
        const user = userEvent.setup()
        let resolveLogin: (response: AxiosResponse<AuthUser>) => void = () => undefined
        vi.mocked(login).mockReturnValue(
            new Promise<AxiosResponse<AuthUser>>((resolve) => {
                resolveLogin = resolve
            }),
        )
        vi.mocked(me).mockResolvedValue({ data: testUser } as AxiosResponse<AuthUser>)
        renderLogin()

        await signInWith(user, 'user@example.com', 'password123')

        const pendingButton = await screen.findByRole('button', { name: 'Signing in…' })
        expect(pendingButton).toBeDisabled()

        resolveLogin({ data: testUser } as AxiosResponse<AuthUser>)
        expect(await screen.findByText('Home page')).toBeInTheDocument()
    })

    it('links to the registration page', () => {
        renderLogin()

        expect(screen.getByRole('link', { name: 'Register' })).toHaveAttribute(
            'href',
            '/register',
        )
    })
})
