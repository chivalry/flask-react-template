import { render, screen, waitFor, within } from '@testing-library/react'
import { AxiosError } from 'axios'
import type { AxiosResponse } from 'axios'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { me } from '../api/auth'
import { getHealth } from '../api/health'
import { usersApi } from '../api/users'
import App from '../App'
import { useAuthStore } from '../store/auth'
import type { AuthUser } from '../types/auth'
import { adminUser, plainUser } from './utils/fixtures'
import Providers from './utils/Providers'

vi.mock('../api/auth')
vi.mock('../api/health')
vi.mock('../api/users')

// The app reads the query client from context, so it renders inside the test providers.
const renderAppAtPath = (path: string) =>
    render(
        <Providers route={path}>
            <App />
        </Providers>,
    )

// The server answers a missing session with 401; only that status signs the visitor
// out, so the helper must reject the way axios would, not with a bare Error.
const signedOut = () => {
    const unauthorized = new AxiosError('Unauthorized', 'ERR_BAD_REQUEST')
    unauthorized.response = { status: 401 } as AxiosResponse
    vi.mocked(me).mockRejectedValue(unauthorized)
}
const signedIn = (user: AuthUser = adminUser) =>
    vi.mocked(me).mockResolvedValue({ data: user } as AxiosResponse<AuthUser>)

const findHomeHeading = () => screen.findByRole('heading', { name: 'Hello, World' })

describe('App', () => {
    beforeEach(() => {
        vi.clearAllMocks()
        useAuthStore.setState({ user: null, isLoading: true })
        vi.mocked(usersApi.list).mockResolvedValue([adminUser, plainUser])
        vi.mocked(getHealth).mockReturnValue(new Promise(() => undefined))
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
        signedIn(plainUser)

        renderAppAtPath('/')

        expect(await findHomeHeading()).toBeInTheDocument()
        const appBar = screen.getByRole('banner')
        expect(within(appBar).getByText('Flask React Template')).toBeInTheDocument()
        expect(within(appBar).getByRole('link', { name: 'Home' })).toHaveAttribute(
            'href',
            '/',
        )
        expect(within(appBar).getByText(plainUser.email)).toBeInTheDocument()
    })

    it('shows an admin the accounts on the home page', async () => {
        signedIn()

        renderAppAtPath('/')

        expect(
            await screen.findByRole('heading', { level: 1, name: 'Users' }),
        ).toBeInTheDocument()
        expect(usersApi.list).toHaveBeenCalledTimes(1)
    })

    it('redirects unknown paths to /', async () => {
        signedIn(plainUser)

        renderAppAtPath('/nope')

        expect(await findHomeHeading()).toBeInTheDocument()
    })

    it('shows the Users tab of the admin section to an admin', async () => {
        signedIn()

        renderAppAtPath('/admin')

        expect(await screen.findByText(plainUser.email)).toBeInTheDocument()
        expect(screen.getByRole('tab', { name: 'Users' })).toHaveAttribute(
            'aria-selected',
            'true',
        )
        expect(screen.getByRole('heading', { name: 'Users' })).toBeInTheDocument()
        expect(usersApi.list).toHaveBeenCalledTimes(1)
    })

    it('sends a non-admin from /admin to the home page', async () => {
        signedIn(plainUser)

        renderAppAtPath('/admin')

        expect(await findHomeHeading()).toBeInTheDocument()
        expect(screen.queryByRole('tab')).not.toBeInTheDocument()
        expect(screen.queryByRole('link', { name: 'Admin' })).not.toBeInTheDocument()
        expect(usersApi.list).not.toHaveBeenCalled()
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

    it('shows the environment badge on the sign-in page', async () => {
        signedOut()
        vi.mocked(getHealth).mockResolvedValue({
            data: { status: 'ok', environment: 'staging' },
        } as AxiosResponse)

        renderAppAtPath('/login')

        expect(await screen.findByRole('status')).toHaveTextContent('STAGING')
        expect(
            await screen.findByRole('heading', { name: 'Sign in' }),
        ).toBeInTheDocument()
    })
})
