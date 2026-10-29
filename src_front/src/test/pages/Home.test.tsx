/** @file Home shows an admin the accounts and everyone else the welcome. */

import { screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { usersApi } from '../../api/users'
import Home from '../../pages/Home'
import { useAuthStore } from '../../store/auth'
import type { AuthUser } from '../../types/auth'
import { adminUser, plainUser } from '../utils/fixtures'
import { renderWithProviders } from '../utils/renderWithProviders'

vi.mock('../../api/users')

describe('Home', () => {
    beforeEach(() => {
        vi.clearAllMocks()
        vi.mocked(usersApi.list).mockResolvedValue([adminUser, plainUser])
    })

    it('shows an admin the accounts', async () => {
        useAuthStore.setState({ user: adminUser, isLoading: false })
        renderWithProviders(<Home />)

        expect(
            await screen.findByRole('heading', { level: 1, name: 'Users' }),
        ).toBeInTheDocument()
        expect(await screen.findByText(plainUser.email)).toBeInTheDocument()
    })

    it.each<[string, AuthUser | null]>([
        ['a user who is not an admin', plainUser],
        ['nobody signed in', null],
    ])('shows %s the welcome and asks for no accounts', async (_who, account) => {
        useAuthStore.setState({ user: account, isLoading: false })
        renderWithProviders(<Home />)

        expect(
            await screen.findByRole('heading', { name: 'Hello, World' }),
        ).toBeInTheDocument()
        expect(usersApi.list).not.toHaveBeenCalled()
    })
})
