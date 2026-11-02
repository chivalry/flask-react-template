/** @file The Account page's provider section lists, links, and unlinks providers. */

import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { listLinkedAccounts, listProviders, unlinkAccount } from '../../../api/oauth'
import LinkedAccounts from '../../../components/account/LinkedAccounts'
import type { OAuthProviderInfo } from '../../../types/auth'
import { findDialog } from '../../utils/dialogQueries'
import { cancelOpenDialog } from '../../utils/dialogs'
import { googleProvider, linkedGoogleAccount } from '../../utils/fixtures'
import { renderWithProviders } from '../../utils/renderWithProviders'

vi.mock('../../../api/oauth')

type UserSession = ReturnType<typeof userEvent.setup>

/** A second provider, which the account has not linked. */
const appleProvider: OAuthProviderInfo = { name: 'apple', label: 'Apple' }

/** What the server answers when the link is the account's last way to sign in. */
const LAST_METHOD = 'Add another way to sign in before removing this one.'

const renderLinkedAccounts = (route = '/account') =>
    renderWithProviders(<LinkedAccounts />, { route, path: '/account' })

/** Wait for the Google link, then open its Unlink confirmation. */
const openUnlinkDialog = async (user: UserSession) => {
    await user.click(await screen.findByRole('button', { name: 'Unlink Google' }))
    return findDialog()
}

describe('LinkedAccounts', () => {
    beforeEach(() => {
        vi.clearAllMocks()
        vi.mocked(listProviders).mockResolvedValue([googleProvider])
        vi.mocked(listLinkedAccounts).mockResolvedValue([linkedGoogleAccount])
    })

    it('lists a link with its provider label and email', async () => {
        renderLinkedAccounts()

        expect(await screen.findByText('Google')).toBeInTheDocument()
        expect(screen.getByText('user@gmail.com')).toBeInTheDocument()
        expect(screen.getByRole('button', { name: 'Unlink Google' })).toBeInTheDocument()
        expect(screen.queryByText('No providers are linked.')).not.toBeInTheDocument()
    })

    it('names a provider by its name once it is no longer enabled', async () => {
        vi.mocked(listProviders).mockResolvedValue([])
        renderLinkedAccounts()

        expect(await screen.findByText('google')).toBeInTheDocument()
        expect(screen.getByRole('button', { name: 'Unlink google' })).toBeInTheDocument()
        expect(listProviders).toHaveBeenCalledTimes(1)
    })

    it('offers to link only the providers not yet linked', async () => {
        vi.mocked(listProviders).mockResolvedValue([googleProvider, appleProvider])
        renderLinkedAccounts()

        expect(await screen.findByRole('link', { name: 'Link Apple' })).toHaveAttribute(
            'href',
            '/api/v1/auth/oauth/apple/start?next=%2Faccount&link=1',
        )
        expect(
            screen.queryByRole('link', { name: 'Link Google' }),
        ).not.toBeInTheDocument()
    })

    it('says no providers are linked and still offers the link button', async () => {
        vi.mocked(listLinkedAccounts).mockResolvedValue([])
        renderLinkedAccounts()

        expect(await screen.findByText('No providers are linked.')).toBeInTheDocument()
        expect(await screen.findByRole('link', { name: 'Link Google' })).toHaveAttribute(
            'href',
            '/api/v1/auth/oauth/google/start?next=%2Faccount&link=1',
        )
    })

    it('shows the message a failed link returns with, and none without', async () => {
        const { unmount } = renderLinkedAccounts('/account?error=already_linked')

        expect(await screen.findByRole('alert')).toHaveTextContent(
            'That account is already linked to a sign-in provider.',
        )
        unmount()

        renderLinkedAccounts()
        expect(await screen.findByText('Google')).toBeInTheDocument()
        expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    })

    it('unlinks after confirming, closes the dialog, and refetches', async () => {
        const user = userEvent.setup()
        vi.mocked(unlinkAccount).mockResolvedValue(undefined)
        renderLinkedAccounts()
        const dialog = await openUnlinkDialog(user)
        expect(dialog.getByText('Stop using Google?')).toBeInTheDocument()
        vi.mocked(listLinkedAccounts).mockResolvedValue([])

        await user.click(dialog.getByRole('button', { name: 'Unlink' }))

        await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
        expect(unlinkAccount).toHaveBeenCalledTimes(1)
        expect(vi.mocked(unlinkAccount).mock.calls[0][0]).toBe('google')
        expect(await screen.findByText('No providers are linked.')).toBeInTheDocument()
        expect(listLinkedAccounts).toHaveBeenCalledTimes(2)
    })

    it('does nothing on Cancel', async () => {
        const user = userEvent.setup()
        renderLinkedAccounts()
        await openUnlinkDialog(user)

        await cancelOpenDialog(user)

        expect(unlinkAccount).not.toHaveBeenCalled()
        expect(screen.getByRole('button', { name: 'Unlink Google' })).toBeInTheDocument()
        expect(listLinkedAccounts).toHaveBeenCalledTimes(1)
    })

    it('keeps the dialog open with the server message on a refusal', async () => {
        const user = userEvent.setup()
        vi.mocked(unlinkAccount).mockRejectedValue(new Error(LAST_METHOD))
        renderLinkedAccounts()
        const dialog = await openUnlinkDialog(user)

        await user.click(dialog.getByRole('button', { name: 'Unlink' }))

        expect(await dialog.findByRole('alert')).toHaveTextContent(LAST_METHOD)
        expect(screen.getByRole('dialog')).toBeInTheDocument()
        expect(listLinkedAccounts).toHaveBeenCalledTimes(1)
    })

    it('shows the query error through QueryState', async () => {
        vi.mocked(listLinkedAccounts).mockRejectedValue(new Error('Something broke.'))
        renderLinkedAccounts()

        expect(await screen.findByRole('alert')).toHaveTextContent('Something broke.')
    })
})
