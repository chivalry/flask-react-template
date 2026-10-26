/** @file AdminRoute admits an admin and sends everyone else to the home page. */

import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it } from 'vitest'

import AdminRoute from '../../components/AdminRoute'
import { useAuthStore } from '../../store/auth'
import type { AuthUser } from '../../types/auth'
import { adminUser, plainUser } from '../utils/fixtures'

// Mounted as App mounts it: a layout route around the admin page.
const renderAdminRouteAtAdmin = () =>
    render(
        <MemoryRouter initialEntries={['/admin']}>
            <Routes>
                <Route path="/" element={<div>Home page</div>} />
                <Route element={<AdminRoute />}>
                    <Route path="/admin" element={<div>Admin page</div>} />
                </Route>
            </Routes>
        </MemoryRouter>,
    )

describe('AdminRoute', () => {
    beforeEach(() => {
        useAuthStore.setState({ user: null, isLoading: false })
    })

    it('renders the admin page for an admin', () => {
        useAuthStore.setState({ user: adminUser })

        renderAdminRouteAtAdmin()

        expect(screen.getByText('Admin page')).toBeInTheDocument()
        expect(screen.queryByText('Home page')).not.toBeInTheDocument()
    })

    it.each<[string, AuthUser | null]>([
        ['a plain user', plainUser],
        ['a visitor without a user', null],
    ])('sends %s to the home page', (_who, user) => {
        useAuthStore.setState({ user })

        renderAdminRouteAtAdmin()

        expect(screen.getByText('Home page')).toBeInTheDocument()
        expect(screen.queryByText('Admin page')).not.toBeInTheDocument()
    })
})
