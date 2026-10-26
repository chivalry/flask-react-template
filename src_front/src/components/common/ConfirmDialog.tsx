/** @file Dialog that asks for confirmation before a destructive action. */

import {
    Alert,
    Button,
    Dialog,
    DialogActions,
    DialogContent,
    DialogContentText,
    DialogTitle,
} from '@mui/material'
import { useState } from 'react'

import { useApiError } from '../../hooks/useApiError'

/** Props accepted by {@link ConfirmDialog}. */
export interface ConfirmDialogProps {
    open: boolean
    title: string
    message: string
    confirmLabel?: string
    onCancel: () => void
    onConfirm: () => Promise<void>
}

/** Props accepted by {@link ConfirmDialogButtons}. */
interface ConfirmDialogButtonsProps {
    confirmLabel: string
    confirmDisabled: boolean
    cancelDisabled: boolean
    onCancel: () => void
    onConfirm: () => void
}

/**
 * Render the Cancel and confirm buttons.
 *
 * @param props - The component props.
 * @returns The dialog actions element.
 */
function ConfirmDialogButtons(props: ConfirmDialogButtonsProps) {
    const { confirmLabel, confirmDisabled, cancelDisabled, onCancel, onConfirm } = props
    return (
        <DialogActions>
            <Button onClick={onCancel} disabled={cancelDisabled}>
                Cancel
            </Button>
            <Button
                color="error"
                variant="contained"
                disabled={confirmDisabled}
                onClick={onConfirm}
            >
                {confirmLabel}
            </Button>
        </DialogActions>
    )
}

/**
 * Ask the viewer to confirm, then run the action and show any failure inline.
 *
 * A rejected `onConfirm` (for example a 409 because the record is in use)
 * shows its message and keeps the dialog open; the caller closes it on
 * success. The confirm button is disabled while the action runs and while the
 * dialog closes: MUI keeps a closing dialog clickable through its fade-out, and
 * a click there would run the action again. While the action runs, Cancel,
 * Escape, and a backdrop click do nothing: a caller that closes whichever dialog
 * is open when the action finishes, as `RecordSection` does, would otherwise
 * close a dialog the viewer opened in the meantime.
 *
 * @param props - The component props.
 * @returns The dialog element.
 */
export default function ConfirmDialog(props: ConfirmDialogProps) {
    const { open, title, message, confirmLabel, onCancel, onConfirm } = props
    const [pending, setPending] = useState(false)
    const { error, onErr, clearError } = useApiError()

    /** Run the confirmed action, recording a failure for display. */
    const handleConfirm = async () => {
        clearError()
        setPending(true)
        try {
            await onConfirm()
        } catch (err: unknown) {
            onErr(err)
        } finally {
            setPending(false)
        }
    }

    /** Dismiss the dialog and forget any earlier failure. */
    const handleCancel = () => {
        clearError()
        onCancel()
    }

    return (
        <Dialog open={open} onClose={pending ? undefined : handleCancel}>
            <DialogTitle>{title}</DialogTitle>
            <DialogContent>
                {error && (
                    <Alert severity="error" sx={{ mb: 2 }}>
                        {error}
                    </Alert>
                )}
                <DialogContentText>{message}</DialogContentText>
            </DialogContent>
            <ConfirmDialogButtons
                confirmLabel={confirmLabel ?? 'Delete'}
                confirmDisabled={pending || !open}
                cancelDisabled={pending}
                onCancel={handleCancel}
                onConfirm={() => void handleConfirm()}
            />
        </Dialog>
    )
}
