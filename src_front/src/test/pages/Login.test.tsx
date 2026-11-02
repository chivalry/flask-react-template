import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { AxiosResponse } from 'axios'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { login } from '../../api/auth'
import { listProviders } from '../../api/oauth'
import Login from '../../pages/Login'
import { useAuthStore } from '../../store/auth'
import type { AuthUser } from '../../types/auth'
import { adminUser, googleProvider } from '../utils/fixtures'

vi.mock('../../api/auth')
vi.mock('../../api/oauth')

// Shows the full location it landed on, so a test can check the query and hash too.
const RequestedPage = () => {
    const { pathname, search, hash } = useLocation()
    return <div>{`Requested page ${pathname}${search}${hash}`}</div>
}

const renderLogin = (state?: unknown, search = '') =>
    render(
        <MemoryRouter initialEntries={[{ pathname: '/login', search, state }]}>
            <Routes>
                <Route path="/login" element={<Login />} />
                <Route path="/" element={<div>Home page</div>} />
                <Route path="/widgets/:widgetId" element={<RequestedPage />} />
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

const renderLoginAndSignIn = async (state: unknown) => {
    const user = userEvent.setup()
    vi.mocked(login).mockResolvedValue({ data: adminUser } as AxiosResponse<AuthUser>)
    renderLogin(state)
    await signInWith(user, 'user@example.com', 'password123')
}

describe('Login', () => {
    beforeEach(() => {
        vi.clearAllMocks()
        useAuthStore.setState({ user: null, isLoading: false })
        vi.mocked(listProviders).mockReturnValue(new Promise(() => undefined))
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

    it('signs in, stores the user, and navigates to / on success', async () => {
        const user = userEvent.setup()
        vi.mocked(login).mockResolvedValue({ data: adminUser } as AxiosResponse<AuthUser>)
        renderLogin()

        await signInWith(user, 'user@example.com', 'password123')

        expect(await screen.findByText('Home page')).toBeInTheDocument()
        expect(login).toHaveBeenCalledWith('user@example.com', 'password123')
        expect(useAuthStore.getState().user).toEqual(adminUser)
    })

    it('returns to the page the guard recorded, with its query and hash', async () => {
        await renderLoginAndSignIn({
            from: { pathname: '/widgets/12', search: '?tab=notes', hash: '#latest' },
        })

        expect(
            await screen.findByText('Requested page /widgets/12?tab=notes#latest'),
        ).toBeInTheDocument()
    })

    it('returns to a recorded page that has no query or hash', async () => {
        await renderLoginAndSignIn({ from: { pathname: '/widgets/12' } })

        expect(await screen.findByText('Requested page /widgets/12')).toBeInTheDocument()
    })

    it('goes to / when the recorded page has no path', async () => {
        await renderLoginAndSignIn({ from: { search: '?tab=notes' } })

        expect(await screen.findByText('Home page')).toBeInTheDocument()
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
        renderLogin()

        await signInWith(user, 'user@example.com', 'password123')

        const pendingButton = await screen.findByRole('button', { name: 'Signing in…' })
        expect(pendingButton).toBeDisabled()

        resolveLogin({ data: adminUser } as AxiosResponse<AuthUser>)
        expect(await screen.findByText('Home page')).toBeInTheDocument()
    })

    it('links to the registration page', () => {
        renderLogin()

        expect(screen.getByRole('link', { name: 'Register' })).toHaveAttribute(
            'href',
            '/register',
        )
    })

    it('shows the message a failed provider sign-in redirects with', () => {
        renderLogin(undefined, '?error=link_required')

        expect(screen.getByRole('alert')).toHaveTextContent(
            'That email already has an account. Sign in, then link it from Account.',
        )
    })

    it('replaces that message with a failed password attempt, in one alert', async () => {
        const user = userEvent.setup()
        vi.mocked(login).mockRejectedValue(new Error('Invalid email or password.'))
        renderLogin(undefined, '?error=link_required')

        await signInWith(user, 'user@example.com', 'wrong-password')

        await waitFor(() =>
            expect(screen.getByRole('alert')).toHaveTextContent(
                'Invalid email or password.',
            ),
        )
        expect(screen.getAllByRole('alert')).toHaveLength(1)
    })

    it('sends a provider sign-in back to the page the guard recorded', async () => {
        vi.mocked(listProviders).mockResolvedValue([googleProvider])
        renderLogin({
            from: { pathname: '/widgets/12', search: '?tab=notes', hash: '#latest' },
        })

        expect(
            await screen.findByRole('link', { name: 'Continue with Google' }),
        ).toHaveAttribute(
            'href',
            '/api/v1/auth/oauth/google/start?next=%2Fwidgets%2F12%3Ftab%3Dnotes%23latest',
        )
    })

    it('places the provider buttons below Sign in and above the footer', async () => {
        vi.mocked(listProviders).mockResolvedValue([googleProvider])
        renderLogin()

        const provider = await screen.findByRole('link', { name: 'Continue with Google' })
        const submit = screen.getByRole('button', { name: 'Sign in' })
        const footer = screen.getByRole('link', { name: 'Register' })
        expect(submit.compareDocumentPosition(provider)).toBe(
            Node.DOCUMENT_POSITION_FOLLOWING,
        )
        expect(provider.compareDocumentPosition(footer)).toBe(
            Node.DOCUMENT_POSITION_FOLLOWING,
        )
    })

    it('shows no provider button and no divider when none is enabled', async () => {
        vi.mocked(listProviders).mockResolvedValue([])
        renderLogin()

        await waitFor(() => expect(listProviders).toHaveBeenCalledTimes(1))
        expect(
            screen.queryByRole('link', { name: /^Continue with/ }),
        ).not.toBeInTheDocument()
        expect(screen.queryByRole('separator')).not.toBeInTheDocument()
    })

    it('hints the email and the current password to the browser', () => {
        renderLogin()

        expect(screen.getByLabelText('Email')).toHaveAttribute('autocomplete', 'email')
        expect(screen.getByLabelText('Password')).toHaveAttribute(
            'autocomplete',
            'current-password',
        )
    })
})
