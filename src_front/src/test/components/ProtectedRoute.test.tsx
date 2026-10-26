import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import ProtectedRoute from '../components/ProtectedRoute'
import { useAuthStore } from '../store/auth'
import type { AuthUser } from '../types/auth'

const testUser: AuthUser = {
    id: 1,
    uuid: 'user-uuid-1',
    email: 'tester@example.com',
    role: 'admin',
    has_password: true,
    created_at: '2026-08-01T00:00:00Z',
    updated_at: '2026-08-01T00:00:00Z',
}

// Shows the login page and the location the guard recorded in the redirect's state.
const LoginStub = () => {
    const from = useLocation().state?.from
    return (
        <>
            <div>Login page</div>
            <div>{`Recorded ${from?.pathname}${from?.search}${from?.hash}`}</div>
        </>
    )
}

const renderProtectedRoute = (path = '/protected') =>
    render(
        <MemoryRouter initialEntries={[path]}>
            <Routes>
                <Route path="/login" element={<LoginStub />} />
                <Route element={<ProtectedRoute />}>
                    <Route path="/protected" element={<div>Protected content</div>} />
                </Route>
            </Routes>
        </MemoryRouter>,
    )

describe('ProtectedRoute', () => {
    beforeEach(() => {
        useAuthStore.setState({ user: null, isLoading: false, sessionCheckFailed: false })
    })

    it('renders nothing while the session check is still in flight', () => {
        useAuthStore.setState({ isLoading: true })

        const { container } = renderProtectedRoute()

        expect(container).toBeEmptyDOMElement()
        expect(screen.queryByText('Login page')).not.toBeInTheDocument()
    })

    it('renders the child route when the auth store has a user', () => {
        useAuthStore.getState().setUser(testUser)

        renderProtectedRoute()

        expect(screen.getByText('Protected content')).toBeInTheDocument()
        expect(screen.queryByText('Login page')).not.toBeInTheDocument()
    })

    it('redirects to /login when the auth store has no user', () => {
        renderProtectedRoute()

        expect(screen.getByText('Login page')).toBeInTheDocument()
        expect(screen.queryByText('Protected content')).not.toBeInTheDocument()
    })

    it('records the requested path, query, and hash in the redirect', () => {
        renderProtectedRoute('/protected?tab=2#top')

        expect(screen.getByText('Recorded /protected?tab=2#top')).toBeInTheDocument()
    })

    it('offers a retry instead of redirecting when the session check failed', () => {
        useAuthStore.setState({ sessionCheckFailed: true })

        renderProtectedRoute()

        expect(screen.getByRole('alert')).toHaveTextContent(
            'Could not reach the server to check your session.',
        )
        expect(screen.queryByText('Login page')).not.toBeInTheDocument()
        expect(screen.queryByText('Protected content')).not.toBeInTheDocument()
    })

    it('runs the session check again when Retry is clicked', async () => {
        const user = userEvent.setup()
        const fetchMe = vi.fn().mockResolvedValue(undefined)
        useAuthStore.setState({ sessionCheckFailed: true, fetchMe })
        renderProtectedRoute()

        await user.click(screen.getByRole('button', { name: 'Retry' }))

        expect(fetchMe).toHaveBeenCalledTimes(1)
    })

    it('still renders the child route for a signed-in user after a failed refresh', () => {
        useAuthStore.setState({ user: testUser, sessionCheckFailed: true })

        renderProtectedRoute()

        expect(screen.getByText('Protected content')).toBeInTheDocument()
        expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    })
})
