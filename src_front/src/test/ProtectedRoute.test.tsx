import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it } from 'vitest'

import ProtectedRoute from '../components/ProtectedRoute'
import { useAuthStore } from '../store/auth'
import type { AuthUser } from '../types/auth'

const testUser: AuthUser = {
    id: 1,
    uuid: 'user-uuid-1',
    email: 'tester@example.com',
    role: 'admin',
    created_at: '2026-08-01T00:00:00Z',
    updated_at: '2026-08-01T00:00:00Z',
}

const renderProtectedRoute = () =>
    render(
        <MemoryRouter initialEntries={['/protected']}>
            <Routes>
                <Route path="/login" element={<div>Login page</div>} />
                <Route element={<ProtectedRoute />}>
                    <Route path="/protected" element={<div>Protected content</div>} />
                </Route>
            </Routes>
        </MemoryRouter>,
    )

describe('ProtectedRoute', () => {
    beforeEach(() => {
        useAuthStore.setState({ user: null, isLoading: false })
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
})
