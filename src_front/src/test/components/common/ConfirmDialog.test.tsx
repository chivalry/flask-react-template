import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import ConfirmDialog from '../../../components/common/ConfirmDialog'
import type { ConfirmDialogProps } from '../../../components/common/ConfirmDialog'
import { pressEscapeInDialog } from '../../utils/dialogs'

const onCancel = vi.fn()
const onConfirm = vi.fn<() => Promise<void>>()

const dialogElement = (overrides: Partial<ConfirmDialogProps> = {}) => (
    <ConfirmDialog
        open
        title="Delete record"
        message="Delete the record Widget?"
        onCancel={onCancel}
        onConfirm={onConfirm}
        {...overrides}
    />
)

const renderDialog = (overrides: Partial<ConfirmDialogProps> = {}) =>
    render(dialogElement(overrides))

/** Open a confirmation whose deletion fails. */
const rejectDeletion = async (user: ReturnType<typeof userEvent.setup>) => {
    onConfirm.mockRejectedValue(new Error('Record is in use.'))
    renderDialog()
    await user.click(screen.getByRole('button', { name: 'Delete' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Record is in use.')
}

describe('ConfirmDialog', () => {
    beforeEach(() => {
        vi.clearAllMocks()
        onConfirm.mockResolvedValue(undefined)
    })

    it('renders the title, the message, and the default Delete label', () => {
        renderDialog()

        const dialog = screen.getByRole('dialog')
        expect(within(dialog).getByText('Delete record')).toBeInTheDocument()
        expect(within(dialog).getByText('Delete the record Widget?')).toBeInTheDocument()
        expect(within(dialog).getByRole('button', { name: 'Delete' })).toBeInTheDocument()
        expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    })

    it('shows a custom confirm label', () => {
        renderDialog({ confirmLabel: 'Remove' })

        expect(screen.getByRole('button', { name: 'Remove' })).toBeInTheDocument()
        expect(screen.queryByRole('button', { name: 'Delete' })).not.toBeInTheDocument()
    })

    it('runs onConfirm and holds the dialog open while it is pending', async () => {
        const user = userEvent.setup()
        let resolveConfirm: () => void = () => undefined
        onConfirm.mockReturnValue(
            new Promise<void>((resolve) => {
                resolveConfirm = resolve
            }),
        )
        renderDialog()

        await user.click(screen.getByRole('button', { name: 'Delete' }))

        expect(onConfirm).toHaveBeenCalledTimes(1)
        expect(screen.getByRole('button', { name: 'Delete' })).toBeDisabled()
        expect(screen.getByRole('button', { name: 'Cancel' })).toBeDisabled()
        // The caller closes whichever dialog is open once the action settles, so a
        // dismissal now would let that close land on the next dialog instead.
        pressEscapeInDialog()
        expect(onCancel).not.toHaveBeenCalled()

        resolveConfirm()

        await waitFor(() =>
            expect(screen.getByRole('button', { name: 'Delete' })).toBeEnabled(),
        )
        expect(screen.getByRole('button', { name: 'Cancel' })).toBeEnabled()
        expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    })

    it('disables the button as soon as the dialog starts closing', () => {
        const { rerender } = renderDialog()
        expect(screen.getByRole('button', { name: 'Delete' })).toBeEnabled()

        rerender(dialogElement({ open: false }))

        // MUI keeps a closing dialog mounted, and clickable, through its exit
        // transition; a second click there would run onConfirm again.
        expect(screen.getByRole('button', { name: 'Delete' })).toBeDisabled()
    })

    it('shows the failure message and stays open when onConfirm rejects', async () => {
        const user = userEvent.setup()
        await rejectDeletion(user)
        expect(screen.getByRole('dialog')).toBeInTheDocument()
        expect(screen.getByRole('button', { name: 'Delete' })).toBeEnabled()
        expect(onCancel).not.toHaveBeenCalled()
    })

    it('clears the error and calls onCancel when Cancel is clicked', async () => {
        const user = userEvent.setup()
        await rejectDeletion(user)

        await user.click(screen.getByRole('button', { name: 'Cancel' }))

        expect(onCancel).toHaveBeenCalledTimes(1)
        expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    })

    it('calls onCancel when Escape is pressed', () => {
        renderDialog()

        pressEscapeInDialog()

        expect(onCancel).toHaveBeenCalledTimes(1)
    })

    it('renders nothing while closed', () => {
        renderDialog({ open: false })

        expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    })
})
