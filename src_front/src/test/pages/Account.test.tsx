/** @file The Account page heads itself, its sign-in providers, and its passkeys. */

import { screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { listLinkedAccounts, listProviders } from '../../api/oauth'
import { passkeysApi } from '../../api/passkeys'
import Account from '../../pages/Account'
import { renderWithProviders } from '../utils/renderWithProviders'

vi.mock('../../api/oauth')
vi.mock('../../api/passkeys')

describe('Account', () => {
    beforeEach(() => {
        vi.clearAllMocks()
        vi.mocked(listProviders).mockReturnValue(new Promise(() => undefined))
        vi.mocked(listLinkedAccounts).mockReturnValue(new Promise(() => undefined))
        vi.mocked(passkeysApi.list).mockResolvedValue([])
    })

    it('heads the page, its sign-in providers, and its passkeys', async () => {
        renderWithProviders(<Account />)

        expect(
            screen.getByRole('heading', { level: 1, name: 'Account' }),
        ).toBeInTheDocument()
        expect(
            screen.getByRole('heading', { level: 2, name: 'Sign-in providers' }),
        ).toBeInTheDocument()
        expect(
            await screen.findByRole('heading', { level: 2, name: 'Passkeys' }),
        ).toBeInTheDocument()
    })
})
