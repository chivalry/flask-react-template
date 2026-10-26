/** @file Check how RecordSection wires its list, form dialog, and optional Delete. */
import { Button, Dialog, DialogActions, DialogTitle } from '@mui/material'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ComponentProps } from 'react'
import { describe, expect, it, vi } from 'vitest'

import RecordSection from '../../../components/common/RecordSection'
import type { RecordDialogProps } from '../../../components/common/RecordSection'
import type { AuthUser } from '../../../types/auth'
import { findDialog, rowContaining } from '../../utils/dialogQueries'
import { cancelOpenDialog, pressEscapeInDialog } from '../../utils/dialogs'
import { adminUser, plainUser } from '../../utils/fixtures'

interface Payload {
    email: string
}

type SectionProps = ComponentProps<typeof RecordSection<AuthUser, Payload>>

const payload: Payload = { email: 'new@example.com' }

/** A form dialog stand-in whose Save submits a fixed payload. */
const formDialog = ({ open, item, onSubmit }: RecordDialogProps<AuthUser, Payload>) => (
    <Dialog open={open}>
        <DialogTitle>{item ? `Edit ${item.email}` : 'Create'}</DialogTitle>
        <DialogActions>
            <Button onClick={() => void onSubmit(payload)}>Save</Button>
        </DialogActions>
    </Dialog>
)

/** Create and update mutations that succeed, without a remove mutation. */
const saveMutations = () => ({
    create: { mutateAsync: vi.fn().mockResolvedValue(plainUser) },
    update: { mutateAsync: vi.fn().mockResolvedValue(plainUser) },
})

/** Create, update, and remove mutations that succeed. */
const allMutations = () => ({
    ...saveMutations(),
    remove: { mutateAsync: vi.fn().mockResolvedValue(undefined) },
})

const renderSection = (props: Partial<SectionProps> & Pick<SectionProps, 'mutations'>) =>
    render(
        <RecordSection<AuthUser, Payload>
            title="Users"
            addLabel="New user"
            emptyText="No users yet."
            items={[adminUser, plainUser]}
            renderPrimary={(account) => account.email}
            renderDialog={formDialog}
            {...props}
        />,
    )

/** Wait until the closing dialog's exit transition has unmounted it. */
const waitForDialogToClose = () =>
    waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())

/** Click a row's Delete and return queries scoped to the confirmation. */
const openDelete = async (user: ReturnType<typeof userEvent.setup>, email: string) => {
    await user.click(rowContaining(email).getByRole('button', { name: 'Delete' }))
    return findDialog()
}

/** Render the section, then confirm the plain user's delete and return the dialog. */
const confirmPlainUserDelete = async (
    user: ReturnType<typeof userEvent.setup>,
    mutations: ReturnType<typeof allMutations>,
) => {
    renderSection({ mutations })
    const dialog = await openDelete(user, plainUser.email)
    await user.click(dialog.getByRole('button', { name: 'Delete' }))
    return dialog
}

describe('RecordSection', () => {
    it('offers only Edit without remove; Add and Edit submit and close', async () => {
        const user = userEvent.setup()
        const mutations = saveMutations()
        const canDelete = vi.fn(() => true)
        renderSection({ mutations, canDelete })

        expect(screen.getAllByRole('button', { name: 'Edit' })).toHaveLength(2)
        expect(screen.queryByRole('button', { name: 'Delete' })).not.toBeInTheDocument()
        expect(canDelete).not.toHaveBeenCalled()

        await user.click(screen.getByRole('button', { name: 'New user' }))
        const createDialog = await findDialog()
        expect(createDialog.getByText('Create')).toBeInTheDocument()
        await user.click(createDialog.getByRole('button', { name: 'Save' }))
        await waitForDialogToClose()
        expect(mutations.create.mutateAsync).toHaveBeenCalledWith(payload)

        const plainRow = rowContaining(plainUser.email)
        await user.click(plainRow.getByRole('button', { name: 'Edit' }))
        const editDialog = await findDialog()
        expect(editDialog.getByText(`Edit ${plainUser.email}`)).toBeInTheDocument()
        await user.click(editDialog.getByRole('button', { name: 'Save' }))
        await waitForDialogToClose()
        expect(mutations.update.mutateAsync).toHaveBeenCalledWith({
            id: plainUser.id,
            payload,
        })
        expect(mutations.create.mutateAsync).toHaveBeenCalledTimes(1)
    })

    it('offers Delete on every row and confirms with the default text', async () => {
        const user = userEvent.setup()
        const mutations = allMutations()
        renderSection({ mutations })

        expect(screen.getAllByRole('button', { name: 'Delete' })).toHaveLength(2)
        const dialog = await openDelete(user, plainUser.email)
        expect(dialog.getByText('Delete record')).toBeInTheDocument()
        expect(dialog.getByText('This cannot be undone.')).toBeInTheDocument()

        await user.click(dialog.getByRole('button', { name: 'Delete' }))
        await waitForDialogToClose()

        expect(mutations.remove.mutateAsync).toHaveBeenCalledWith(plainUser.id)
    })

    it('hides Delete where canDelete refuses and shows the custom text', async () => {
        const user = userEvent.setup()
        const mutations = allMutations()
        renderSection({
            mutations,
            canDelete: (account) => account.id !== adminUser.id,
            deleteTitle: 'Delete user',
            deleteMessage: (account) => `Delete ${account.email}?`,
        })

        const adminRow = rowContaining(adminUser.email)
        expect(adminRow.getByRole('button', { name: 'Edit' })).toBeInTheDocument()
        expect(adminRow.queryByRole('button', { name: 'Delete' })).not.toBeInTheDocument()
        const dialog = await openDelete(user, plainUser.email)
        expect(dialog.getByText('Delete user')).toBeInTheDocument()
        expect(dialog.getByText(`Delete ${plainUser.email}?`)).toBeInTheDocument()
        expect(dialog.queryByText('This cannot be undone.')).not.toBeInTheDocument()

        await cancelOpenDialog(user)

        expect(mutations.remove.mutateAsync).not.toHaveBeenCalled()
    })

    it('keeps the confirmation open until a slow delete settles', async () => {
        const user = userEvent.setup()
        const mutations = allMutations()
        let resolveRemove: () => void = () => undefined
        mutations.remove.mutateAsync.mockReturnValue(
            new Promise<void>((resolve) => {
                resolveRemove = resolve
            }),
        )

        const dialog = await confirmPlainUserDelete(user, mutations)

        expect(dialog.getByRole('button', { name: 'Cancel' })).toBeDisabled()
        pressEscapeInDialog()
        // Dismissing clears the selected record at once, which blanks the message of
        // the closing confirmation; a held-open one keeps it.
        expect(dialog.getByText('This cannot be undone.')).toBeInTheDocument()

        resolveRemove()

        await waitForDialogToClose()
        expect(mutations.remove.mutateAsync).toHaveBeenCalledWith(plainUser.id)
    })

    it('keeps the confirmation open with the error when the delete fails', async () => {
        const user = userEvent.setup()
        const mutations = allMutations()
        mutations.remove.mutateAsync.mockRejectedValue(new Error('User is in use.'))

        const dialog = await confirmPlainUserDelete(user, mutations)

        expect(await dialog.findByRole('alert')).toHaveTextContent('User is in use.')
        expect(mutations.remove.mutateAsync).toHaveBeenCalledWith(plainUser.id)
        expect(screen.getByRole('dialog')).toBeInTheDocument()
        // ConfirmDialog disables the button once its dialog starts closing.
        expect(dialog.getByRole('button', { name: 'Delete' })).toBeEnabled()
    })
})
