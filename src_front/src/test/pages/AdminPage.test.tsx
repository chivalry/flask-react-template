/** @file The admin page lands on its first section and selects that section's tab. */

import { screen } from '@testing-library/react'
import { useLocation } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import AdminPage from '../../pages/AdminPage'
import { renderWithProviders } from '../utils/renderWithProviders'

vi.mock('../../components/admin/UsersAdmin', () => ({
    default: () => <div>Users section</div>,
}))

/** Show the router's current path, so a test can see where a redirect landed. */
function CurrentPath() {
    return <div>{`At ${useLocation().pathname}`}</div>
}

// Mounted as App mounts it, on a splat route, so the sections are descendant routes.
const renderAdminPageAt = (route: string) =>
    renderWithProviders(
        <>
            <AdminPage />
            <CurrentPath />
        </>,
        { route, path: '/admin/*' },
    )

describe('AdminPage', () => {
    it.each(['/admin', '/admin/nope', '/admin/users/extra'])(
        'redirects %s to the Users section and selects its tab',
        async (route) => {
            renderAdminPageAt(route)

            expect(await screen.findByText('Users section')).toBeInTheDocument()
            expect(screen.getByText('At /admin/users')).toBeInTheDocument()
            const tab = screen.getByRole('tab', { name: 'Users' })
            expect(tab).toHaveAttribute('href', '/admin/users')
            expect(tab).toHaveAttribute('aria-selected', 'true')
        },
    )
})
