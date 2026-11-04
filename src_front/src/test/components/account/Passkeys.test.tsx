/** @file The Account page's passkey section lists, adds, renames, and deletes them. */

import { browserSupportsWebAuthn } from '@simplewebauthn/browser'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { passkeysApi } from '../../../api/passkeys'
import Passkeys from '../../../components/account/Passkeys'
import type { Passkey } from '../../../types/auth'
import { describePasskeyUse } from '../../../utils/passkeys'
import { findDialog, rowContaining } from '../../utils/dialogQueries'
import { laptopPasskey } from '../../utils/fixtures'
import { renderWithProviders } from '../../utils/renderWithProviders'

vi.mock('@simplewebauthn/browser', async (importOriginal) =>
    (await import('../../utils/webauthnMock')).mockWebAuthnBrowser(importOriginal),
)
vi.mock('../../../api/passkeys')

type UserSession = ReturnType<typeof userEvent.setup>

/** What the server answers when the passkey is the account's last way to sign in. */
const LAST_METHOD = 'Add another way to sign in before removing this one.'

/** The passkey an Add named Phone saves. */
const phonePasskey: Passkey = { ...laptopPasskey, id: 4, nickname: 'Phone' }

/** Wait for the list, open the Add dialog, and return queries scoped to it. */
const openAddDialog = async (user: UserSession) => {
    await user.click(await screen.findByRole('button', { name: 'Add passkey' }))
    return findDialog()
}

/** Wait for the laptop passkey, press one of its row actions, and return the dialog. */
const openRowDialog = async (user: UserSession, action: 'Edit' | 'Delete') => {
    await screen.findByText('Laptop')
    await user.click(rowContaining('Laptop').getByRole('button', { name: action }))
    return findDialog()
}

/** Wait until the closing dialog's exit transition has unmounted it. */
const waitForDialogToClose = () =>
    waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())

describe('Passkeys', () => {
    beforeEach(() => {
        vi.clearAllMocks()
        vi.mocked(browserSupportsWebAuthn).mockReturnValue(true)
        vi.mocked(passkeysApi.list).mockResolvedValue([laptopPasskey])
    })

    it('lists a passkey with its name and when it was added and used', async () => {
        renderWithProviders(<Passkeys />)

        expect(await screen.findByText('Laptop')).toBeInTheDocument()
        expect(screen.getByText(describePasskeyUse(laptopPasskey))).toBeInTheDocument()
        expect(screen.getByRole('heading', { level: 2, name: 'Passkeys' })).toBeVisible()
        expect(screen.queryByText('No passkeys yet.')).not.toBeInTheDocument()
    })

    it('says when the account has no passkeys yet', async () => {
        vi.mocked(passkeysApi.list).mockResolvedValue([])

        renderWithProviders(<Passkeys />)

        expect(await screen.findByText('No passkeys yet.')).toBeInTheDocument()
    })

    it('stands in for a passkey without a nickname', async () => {
        vi.mocked(passkeysApi.list).mockResolvedValue([
            { ...laptopPasskey, nickname: null },
        ])

        renderWithProviders(<Passkeys />)

        expect(await screen.findByText('Unnamed passkey')).toBeInTheDocument()
    })

    it('adds a passkey under its nickname, then closes and refetches', async () => {
        const user = userEvent.setup()
        vi.mocked(passkeysApi.create).mockResolvedValue(phonePasskey)
        renderWithProviders(<Passkeys />)
        const dialog = await openAddDialog(user)
        expect(dialog.getByText('Add a passkey')).toBeInTheDocument()
        vi.mocked(passkeysApi.list).mockResolvedValue([laptopPasskey, phonePasskey])

        await user.type(dialog.getByLabelText('Nickname'), 'Phone')
        await user.click(dialog.getByRole('button', { name: 'Continue' }))

        await waitForDialogToClose()
        expect(passkeysApi.create).toHaveBeenCalledExactlyOnceWith({ nickname: 'Phone' })
        expect(await screen.findByText('Phone')).toBeInTheDocument()
        expect(passkeysApi.list).toHaveBeenCalledTimes(2)
    })

    it('adds a passkey without a nickname as null', async () => {
        const user = userEvent.setup()
        vi.mocked(passkeysApi.create).mockResolvedValue({
            ...phonePasskey,
            nickname: null,
        })
        renderWithProviders(<Passkeys />)
        const dialog = await openAddDialog(user)

        await user.click(dialog.getByRole('button', { name: 'Continue' }))

        await waitForDialogToClose()
        expect(passkeysApi.create).toHaveBeenCalledExactlyOnceWith({ nickname: null })
    })

    it('keeps the Add dialog open with why the browser made no passkey', async () => {
        const user = userEvent.setup()
        vi.mocked(passkeysApi.create).mockRejectedValue(
            new Error('Passkey setup was cancelled.'),
        )
        renderWithProviders(<Passkeys />)
        const dialog = await openAddDialog(user)

        await user.click(dialog.getByRole('button', { name: 'Continue' }))

        expect(await dialog.findByRole('alert')).toHaveTextContent(
            'Passkey setup was cancelled.',
        )
        expect(screen.getByRole('dialog')).toBeInTheDocument()
        expect(passkeysApi.list).toHaveBeenCalledTimes(1)
    })

    it('renames a passkey from a dialog that starts with its nickname', async () => {
        const user = userEvent.setup()
        vi.mocked(passkeysApi.update).mockResolvedValue({
            ...laptopPasskey,
            nickname: 'Work laptop',
        })
        renderWithProviders(<Passkeys />)
        const dialog = await openRowDialog(user, 'Edit')
        expect(dialog.getByText('Rename passkey')).toBeInTheDocument()
        const nickname = dialog.getByLabelText('Nickname')
        expect(nickname).toHaveValue('Laptop')

        await user.clear(nickname)
        await user.type(nickname, 'Work laptop')
        await user.click(dialog.getByRole('button', { name: 'Save' }))

        await waitForDialogToClose()
        expect(passkeysApi.update).toHaveBeenCalledExactlyOnceWith(3, {
            nickname: 'Work laptop',
        })
    })

    it('deletes a passkey once the warning is confirmed', async () => {
        const user = userEvent.setup()
        vi.mocked(passkeysApi.remove).mockResolvedValue(undefined)
        renderWithProviders(<Passkeys />)
        const dialog = await openRowDialog(user, 'Delete')
        expect(dialog.getByText('Delete passkey')).toBeInTheDocument()
        expect(
            dialog.getByText(
                'Laptop will stop signing in here. Remove it from your device as well.',
            ),
        ).toBeInTheDocument()

        await user.click(dialog.getByRole('button', { name: 'Delete' }))

        await waitForDialogToClose()
        expect(passkeysApi.remove).toHaveBeenCalledExactlyOnceWith(3)
    })

    it('keeps the confirmation open with the reason a delete was refused', async () => {
        const user = userEvent.setup()
        vi.mocked(passkeysApi.remove).mockRejectedValue(new Error(LAST_METHOD))
        renderWithProviders(<Passkeys />)
        const dialog = await openRowDialog(user, 'Delete')

        await user.click(dialog.getByRole('button', { name: 'Delete' }))

        expect(await dialog.findByRole('alert')).toHaveTextContent(LAST_METHOD)
        expect(screen.getByRole('dialog')).toBeInTheDocument()
        expect(passkeysApi.remove).toHaveBeenCalledExactlyOnceWith(3)
    })

    it('turns Add off, and says why, in a browser without WebAuthn', async () => {
        vi.mocked(browserSupportsWebAuthn).mockReturnValue(false)

        renderWithProviders(<Passkeys />)

        expect(await screen.findByRole('button', { name: 'Add passkey' })).toBeDisabled()
        expect(
            screen.getByText('This browser cannot create passkeys.'),
        ).toBeInTheDocument()
    })

    it('refuses a nickname of 65 characters and sends nothing', async () => {
        const user = userEvent.setup()
        renderWithProviders(<Passkeys />)
        const dialog = await openAddDialog(user)

        await user.click(dialog.getByLabelText('Nickname'))
        await user.paste('x'.repeat(65))
        await user.click(dialog.getByRole('button', { name: 'Continue' }))

        expect(await dialog.findByText('Use 64 characters or fewer.')).toBeInTheDocument()
        expect(passkeysApi.create).not.toHaveBeenCalled()
    })
})
