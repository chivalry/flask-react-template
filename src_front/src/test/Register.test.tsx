import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { AxiosResponse } from 'axios'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { register } from '../api/auth'
import Register from '../pages/Register'
import { useAuthStore } from '../store/auth'
import type { AuthUser } from '../types/auth'

vi.mock('../api/auth')

const testUser: AuthUser = {
    id: 2,
    uuid: 'user-uuid-2',
    email: 'new@example.com',
    role: 'user',
    created_at: '2026-08-01T00:00:00Z',
    updated_at: '2026-08-01T00:00:00Z',
}

const renderRegister = () =>
    render(
        <MemoryRouter initialEntries={['/register']}>
            <Routes>
                <Route path="/register" element={<Register />} />
                <Route path="/" element={<div>Home page</div>} />
            </Routes>
        </MemoryRouter>,
    )

const fillRegistrationForm = async (
    user: ReturnType<typeof userEvent.setup>,
    fields: { email: string; password: string; confirmPassword: string },
) => {
    await user.type(screen.getByLabelText('Email'), fields.email)
    await user.type(screen.getByLabelText('Password'), fields.password)
    await user.type(screen.getByLabelText('Confirm password'), fields.confirmPassword)
}

describe('Register', () => {
    beforeEach(() => {
        vi.clearAllMocks()
        useAuthStore.setState({ user: null, isLoading: false })
    })

    it('shows the invalid email message and does not call the API', async () => {
        const user = userEvent.setup()
        renderRegister()

        await fillRegistrationForm(user, {
            email: 'not-an-email',
            password: 'password123',
            confirmPassword: 'password123',
        })
        await user.click(screen.getByRole('button', { name: 'Create account' }))

        expect(await screen.findByText('Enter a valid email.')).toBeInTheDocument()
        expect(register).not.toHaveBeenCalled()
    })

    it('shows the short password message and does not call the API', async () => {
        const user = userEvent.setup()
        renderRegister()

        await fillRegistrationForm(user, {
            email: 'new@example.com',
            password: 'short12',
            confirmPassword: 'short12',
        })
        await user.click(screen.getByRole('button', { name: 'Create account' }))

        expect(
            await screen.findByText('Password must be at least 8 characters.'),
        ).toBeInTheDocument()
        expect(register).not.toHaveBeenCalled()
    })

    it('shows the mismatched password message and does not call the API', async () => {
        const user = userEvent.setup()
        renderRegister()

        await fillRegistrationForm(user, {
            email: 'new@example.com',
            password: 'password123',
            confirmPassword: 'password124',
        })
        await user.click(screen.getByRole('button', { name: 'Create account' }))

        expect(await screen.findByText('Passwords do not match.')).toBeInTheDocument()
        expect(register).not.toHaveBeenCalled()
    })

    it('registers, stores the signed-in user, and navigates to /', async () => {
        const user = userEvent.setup()
        vi.mocked(register).mockResolvedValue({
            data: testUser,
        } as AxiosResponse<AuthUser>)
        renderRegister()

        await fillRegistrationForm(user, {
            email: 'new@example.com',
            password: 'password123',
            confirmPassword: 'password123',
        })
        await user.click(screen.getByRole('button', { name: 'Create account' }))

        expect(await screen.findByText('Home page')).toBeInTheDocument()
        expect(register).toHaveBeenCalledWith('new@example.com', 'password123')
        expect(useAuthStore.getState().user).toEqual(testUser)
    })

    it('shows the server-provided message when registration fails', async () => {
        const user = userEvent.setup()
        // The client's interceptor has already copied the backend's `{ error }`
        // text into the rejection's message by the time the page sees it.
        vi.mocked(register).mockRejectedValue(new Error('Email is already registered.'))
        renderRegister()

        await fillRegistrationForm(user, {
            email: 'taken@example.com',
            password: 'password123',
            confirmPassword: 'password123',
        })
        await user.click(screen.getByRole('button', { name: 'Create account' }))

        expect(await screen.findByRole('alert')).toHaveTextContent(
            'Email is already registered.',
        )
        expect(useAuthStore.getState().user).toBeNull()
    })

    it('shows the fallback message when the failure is not an Error', async () => {
        const user = userEvent.setup()
        vi.mocked(register).mockRejectedValue({ response: { status: 500 } })
        renderRegister()

        await fillRegistrationForm(user, {
            email: 'new@example.com',
            password: 'password123',
            confirmPassword: 'password123',
        })
        await user.click(screen.getByRole('button', { name: 'Create account' }))

        expect(await screen.findByRole('alert')).toHaveTextContent('Registration failed.')
        expect(useAuthStore.getState().user).toBeNull()
    })

    it('links to the sign-in page', () => {
        renderRegister()

        expect(screen.getByRole('link', { name: 'Sign in' })).toHaveAttribute(
            'href',
            '/login',
        )
    })
})
