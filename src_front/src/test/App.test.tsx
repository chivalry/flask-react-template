import { render, screen, waitFor, within } from '@testing-library/react'
import { AxiosError } from 'axios'
import type { AxiosResponse } from 'axios'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { me } from '../api/auth'
import App from '../App'
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

const renderAppAtPath = (path: string) =>
    render(
        <MemoryRouter initialEntries={[path]}>
            <App />
        </MemoryRouter>,
    )

// The server answers a missing session with 401; only that status signs the visitor
// out, so the helper must reject the way axios would, not with a bare Error.
const signedOut = () => {
    const unauthorized = new AxiosError('Unauthorized', 'ERR_BAD_REQUEST')
    unauthorized.response = { status: 401 } as AxiosResponse
    vi.mocked(me).mockRejectedValue(unauthorized)
}
const signedIn = () =>
    vi.mocked(me).mockResolvedValue({ data: testUser } as AxiosResponse<AuthUser>)

describe('App', () => {
    beforeEach(() => {
        vi.clearAllMocks()
        useAuthStore.setState({ user: null, isLoading: true })
    })

    it('asks the server who is signed in on mount', async () => {
        signedOut()

        renderAppAtPath('/login')

        await waitFor(() => expect(useAuthStore.getState().isLoading).toBe(false))
        expect(me).toHaveBeenCalledTimes(1)
    })

    it('renders nothing for a protected route until the session check settles', () => {
        vi.mocked(me).mockReturnValue(new Promise(() => undefined))

        renderAppAtPath('/')

        expect(screen.queryByRole('heading')).not.toBeInTheDocument()
        expect(screen.queryByRole('banner')).not.toBeInTheDocument()
    })

    it('redirects a signed-out visitor from / to the login page', async () => {
        signedOut()

        renderAppAtPath('/')

        expect(
            await screen.findByRole('heading', { name: 'Sign in' }),
        ).toBeInTheDocument()
    })

    it('renders the shell and the home page at / when signed in', async () => {
        signedIn()

        renderAppAtPath('/')

        expect(
            await screen.findByRole('heading', { name: 'Hello, World' }),
        ).toBeInTheDocument()
        const appBar = screen.getByRole('banner')
        expect(within(appBar).getByText('Flask React Template')).toBeInTheDocument()
        expect(within(appBar).getByRole('link', { name: 'Home' })).toHaveAttribute(
            'href',
            '/',
        )
        expect(within(appBar).getByText('tester@example.com')).toBeInTheDocument()
    })

    it('redirects unknown paths to /', async () => {
        signedIn()

        renderAppAtPath('/nope')

        expect(
            await screen.findByRole('heading', { name: 'Hello, World' }),
        ).toBeInTheDocument()
    })

    it('renders the login page at /login', async () => {
        signedOut()

        renderAppAtPath('/login')

        expect(
            await screen.findByRole('heading', { name: 'Sign in' }),
        ).toBeInTheDocument()
        await waitFor(() => expect(useAuthStore.getState().isLoading).toBe(false))
    })

    it('renders the register page at /register', async () => {
        signedOut()

        renderAppAtPath('/register')

        expect(
            await screen.findByRole('heading', { name: 'Create account' }),
        ).toBeInTheDocument()
        await waitFor(() => expect(useAuthStore.getState().isLoading).toBe(false))
    })
})
