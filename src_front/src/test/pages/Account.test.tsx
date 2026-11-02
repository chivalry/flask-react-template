/** @file The Account page heads itself and its sign-in providers section. */

import { screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { listLinkedAccounts, listProviders } from '../../api/oauth'
import Account from '../../pages/Account'
import { renderWithProviders } from '../utils/renderWithProviders'

vi.mock('../../api/oauth')

describe('Account', () => {
    beforeEach(() => {
        vi.clearAllMocks()
        vi.mocked(listProviders).mockReturnValue(new Promise(() => undefined))
        vi.mocked(listLinkedAccounts).mockReturnValue(new Promise(() => undefined))
    })

    it('heads the page and its sign-in providers section', () => {
        renderWithProviders(<Account />)

        expect(
            screen.getByRole('heading', { level: 1, name: 'Account' }),
        ).toBeInTheDocument()
        expect(
            screen.getByRole('heading', { level: 2, name: 'Sign-in providers' }),
        ).toBeInTheDocument()
    })
})
