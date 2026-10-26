/** @file The Users tab lists accounts, creates and edits them, and never deletes one. */

import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { usersApi } from '../../../api/users'
import UsersAdmin from '../../../components/admin/UsersAdmin'
import { useAuthStore } from '../../../store/auth'
import type { User } from '../../../types/users'
import { findDialog, rowContaining } from '../../utils/dialogQueries'
import { pressEscapeInDialog } from '../../utils/dialogs'
import { adminUser, plainUser } from '../../utils/fixtures'
import { renderWithProviders } from '../../utils/renderWithProviders'

vi.mock('../../../api/users')

type UserSession = ReturnType<typeof userEvent.setup>

const inactiveUser: User = {
    ...plainUser,
    id: 3,
    uuid: 'user-uuid-3',
    email: 'former@example.com',
    is_active: false,
}

const KEEP_PASSWORD_TEXT = 'Leave blank to keep the current password.'

const renderUsersAdmin = () => renderWithProviders(<UsersAdmin />)

/** Wait for the list, then open the New user dialog. */
const openNewUserDialog = async (user: UserSession) => {
    await screen.findByText(plainUser.email)
    await user.click(screen.getByRole('button', { name: 'New user' }))
    return findDialog()
}

/** Wait for the list, then open the edit dialog for the account with the given email. */
const openEditDialog = async (user: UserSession, email: string) => {
    await screen.findByText(email)
    await user.click(rowContaining(email).getByRole('button', { name: 'Edit' }))
    return findDialog()
}

const roleSelect = (dialog: ReturnType<typeof within>) =>
    dialog.getByRole('combobox', { name: /Role/ })
const activeSwitch = (dialog: ReturnType<typeof within>) =>
    dialog.getByRole('checkbox', { name: 'Active' })

describe('UsersAdmin', () => {
    beforeEach(() => {
        vi.clearAllMocks()
        useAuthStore.setState({ user: null, isLoading: false })
        vi.mocked(usersApi.list).mockResolvedValue([adminUser, plainUser, inactiveUser])
    })

    it('describes each account by its role and whether it is deactivated', async () => {
        renderUsersAdmin()

        expect(await screen.findByRole('heading', { name: 'Users' })).toBeInTheDocument()
        expect(rowContaining(adminUser.email).getByText('admin')).toBeInTheDocument()
        expect(rowContaining(plainUser.email).getByText('user')).toBeInTheDocument()
        expect(
            rowContaining(inactiveUser.email).getByText('user · inactive'),
        ).toBeInTheDocument()
    })

    it('says so when there are no users yet', async () => {
        vi.mocked(usersApi.list).mockResolvedValue([])
        renderUsersAdmin()

        expect(await screen.findByText('No users yet.')).toBeInTheDocument()
    })

    it('offers Edit but never Delete', async () => {
        renderUsersAdmin()
        await screen.findByText(plainUser.email)

        expect(screen.getAllByRole('button', { name: 'Edit' })).toHaveLength(3)
        expect(screen.queryByRole('button', { name: 'Delete' })).not.toBeInTheDocument()
    })

    it('rejects a password shorter than 8 characters for a new user', async () => {
        const user = userEvent.setup()
        renderUsersAdmin()
        const dialog = await openNewUserDialog(user)

        expect(dialog.getByRole('heading', { name: 'New user' })).toBeInTheDocument()
        expect(dialog.queryByText(KEEP_PASSWORD_TEXT)).not.toBeInTheDocument()
        await user.type(dialog.getByLabelText('Email'), 'new@example.com')
        await user.type(dialog.getByLabelText('Password'), 'short12')
        await user.click(dialog.getByRole('button', { name: 'Save' }))

        expect(
            await dialog.findByText('Password must be at least 8 characters.'),
        ).toBeInTheDocument()
        expect(usersApi.create).not.toHaveBeenCalled()
    })

    it('creates a user with the chosen role', async () => {
        const user = userEvent.setup()
        vi.mocked(usersApi.create).mockResolvedValue({
            ...plainUser,
            id: 4,
            uuid: 'user-uuid-4',
            email: 'new@example.com',
            role: 'admin',
        })
        renderUsersAdmin()
        const dialog = await openNewUserDialog(user)

        await user.type(dialog.getByLabelText('Email'), 'new@example.com')
        await user.type(dialog.getByLabelText('Password'), 'longenough')
        await user.click(roleSelect(dialog))
        await user.click(await screen.findByRole('option', { name: 'Admin' }))
        await user.click(await dialog.findByRole('button', { name: 'Save' }))

        await waitFor(() =>
            expect(usersApi.create).toHaveBeenCalledWith({
                email: 'new@example.com',
                password: 'longenough',
                role: 'admin',
                is_active: true,
            }),
        )
        await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    })

    it('edits another user, keeping the password when left blank', async () => {
        const user = userEvent.setup()
        vi.mocked(usersApi.update).mockResolvedValue(plainUser)
        renderUsersAdmin()
        const dialog = await openEditDialog(user, plainUser.email)

        expect(dialog.getByRole('heading', { name: 'Edit user' })).toBeInTheDocument()
        expect(dialog.getByLabelText('Email')).toHaveValue(plainUser.email)
        expect(dialog.getByLabelText('New password')).toHaveValue('')
        expect(dialog.getByText(KEEP_PASSWORD_TEXT)).toBeInTheDocument()
        expect(roleSelect(dialog)).not.toHaveAttribute('aria-disabled')
        expect(activeSwitch(dialog)).toBeEnabled()

        await user.click(dialog.getByRole('button', { name: 'Save' }))

        await waitFor(() =>
            expect(usersApi.update).toHaveBeenCalledWith(plainUser.id, {
                email: plainUser.email,
                role: 'user',
                is_active: true,
            }),
        )
        expect(vi.mocked(usersApi.update).mock.calls[0][1]).not.toHaveProperty('password')
        await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    })

    it('tells the admin a passwordless account stays without one', async () => {
        const user = userEvent.setup()
        const passwordless: User = {
            ...plainUser,
            email: 'provider@example.com',
            has_password: false,
        }
        vi.mocked(usersApi.list).mockResolvedValue([adminUser, passwordless])
        renderUsersAdmin()
        const dialog = await openEditDialog(user, passwordless.email)

        expect(
            dialog.getByText(
                'This account has no password; leave blank to keep it that way.',
            ),
        ).toBeInTheDocument()
        expect(dialog.queryByText(KEEP_PASSWORD_TEXT)).not.toBeInTheDocument()
    })

    it('sends a new password when one is entered', async () => {
        const user = userEvent.setup()
        vi.mocked(usersApi.update).mockResolvedValue(plainUser)
        renderUsersAdmin()
        const dialog = await openEditDialog(user, plainUser.email)

        await user.type(dialog.getByLabelText('New password'), 'newpassword1')
        await user.click(dialog.getByRole('button', { name: 'Save' }))

        await waitFor(() =>
            expect(usersApi.update).toHaveBeenCalledWith(plainUser.id, {
                email: plainUser.email,
                password: 'newpassword1',
                role: 'user',
                is_active: true,
            }),
        )
    })

    it('keeps a slow save open until it settles', async () => {
        const user = userEvent.setup()
        let resolveUpdate: (account: User) => void = () => undefined
        vi.mocked(usersApi.update).mockReturnValue(
            new Promise<User>((resolve) => {
                resolveUpdate = resolve
            }),
        )
        renderUsersAdmin()
        const dialog = await openEditDialog(user, plainUser.email)

        await user.click(dialog.getByRole('button', { name: 'Save' }))

        await waitFor(() =>
            expect(dialog.getByRole('button', { name: 'Cancel' })).toBeDisabled(),
        )
        pressEscapeInDialog()
        // Dismissing clears the edited account at once, which retitles the closing
        // dialog "New user"; a held-open one keeps its title.
        expect(dialog.getByRole('heading', { name: 'Edit user' })).toBeInTheDocument()

        resolveUpdate(plainUser)

        await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    })

    it('locks the role and active switch on the signed-in admin', async () => {
        const user = userEvent.setup()
        useAuthStore.setState({ user: adminUser })
        renderUsersAdmin()
        const dialog = await openEditDialog(user, adminUser.email)

        expect(roleSelect(dialog)).toHaveAttribute('aria-disabled', 'true')
        expect(activeSwitch(dialog)).toBeDisabled()
    })

    it('leaves the role and active switch enabled on another user', async () => {
        const user = userEvent.setup()
        useAuthStore.setState({ user: adminUser })
        renderUsersAdmin()
        const dialog = await openEditDialog(user, plainUser.email)

        expect(roleSelect(dialog)).not.toHaveAttribute('aria-disabled')
        expect(activeSwitch(dialog)).toBeEnabled()
    })
})
