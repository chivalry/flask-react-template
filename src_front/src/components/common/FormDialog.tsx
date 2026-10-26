/** @file Dialog hosting a react-hook-form form validated by a zod schema. */

import { zodResolver } from '@hookform/resolvers/zod'
import {
    Alert,
    Button,
    Dialog,
    DialogActions,
    DialogContent,
    DialogTitle,
} from '@mui/material'
import { useState } from 'react'
import type { ReactNode } from 'react'
import { FormProvider, useForm } from 'react-hook-form'
import type { DefaultValues, FieldValues } from 'react-hook-form'
import type { ZodType } from 'zod'

import { useApiError } from '../../hooks/useApiError'

/** Props accepted by {@link FormDialog}. */
export interface FormDialogProps<
    TInput extends FieldValues,
    TOutput extends FieldValues,
> {
    open: boolean
    title: string
    schema: ZodType<TOutput, TInput>
    defaultValues: DefaultValues<TInput>
    submitLabel?: string
    onClose: () => void
    onSubmit: (values: TOutput) => Promise<void>
    children: ReactNode
}

/** Props accepted by {@link FormDialogBody}. */
interface FormDialogBodyProps<
    TInput extends FieldValues,
    TOutput extends FieldValues,
> extends FormDialogProps<TInput, TOutput> {
    /** Whether the caller's `onSubmit` is still running. */
    pending: boolean
}

/** Props accepted by {@link FormDialogButtons}. */
interface FormDialogButtonsProps {
    submitLabel: string
    submitting: boolean
    cancelDisabled: boolean
    onClose: () => void
}

/**
 * Render the Cancel and submit buttons.
 *
 * @param props - The component props.
 * @returns The dialog actions element.
 */
function FormDialogButtons(props: FormDialogButtonsProps) {
    const { submitLabel, submitting, cancelDisabled, onClose } = props
    return (
        <DialogActions>
            <Button onClick={onClose} disabled={cancelDisabled}>
                Cancel
            </Button>
            <Button type="submit" variant="contained" disabled={submitting}>
                {submitLabel}
            </Button>
        </DialogActions>
    )
}

/**
 * Render the form, its error alert, and the dialog buttons.
 *
 * The dialog unmounts its content once closed, so every opening starts from the
 * given default values without an explicit reset. Until then the content stays
 * mounted through the fade-out, so the submit button is disabled while `open` is
 * false: a second click there would reach the caller's handler after it had
 * already cleared its editing state. Cancel is disabled while `pending`.
 *
 * @param props - The component props.
 * @returns The form element.
 */
function FormDialogBody<TInput extends FieldValues, TOutput extends FieldValues>(
    props: FormDialogBodyProps<TInput, TOutput>,
) {
    const { open, title, submitLabel, pending, onClose, onSubmit, children } = props
    const methods = useForm<TInput, unknown, TOutput>({
        resolver: zodResolver(props.schema),
        defaultValues: props.defaultValues,
    })
    const { error, onErr, clearError } = useApiError()

    /**
     * Run the caller's submit handler, keeping the dialog open on failure.
     *
     * @param values - The validated form values.
     */
    const submit = async (values: TOutput) => {
        clearError()
        try {
            await onSubmit(values)
        } catch (err: unknown) {
            onErr(err)
        }
    }

    return (
        <FormProvider {...methods}>
            <form onSubmit={methods.handleSubmit(submit)} noValidate>
                <DialogTitle>{title}</DialogTitle>
                <DialogContent>
                    {error && (
                        <Alert severity="error" sx={{ mb: 2 }}>
                            {error}
                        </Alert>
                    )}
                    {children}
                </DialogContent>
                <FormDialogButtons
                    submitLabel={submitLabel ?? 'Save'}
                    submitting={methods.formState.isSubmitting || !open}
                    cancelDisabled={pending}
                    onClose={onClose}
                />
            </form>
        </FormProvider>
    )
}

/**
 * Show a form in a dialog and submit it through the caller's handler.
 *
 * A rejected `onSubmit` shows its message above the fields and leaves the
 * dialog open; the caller closes it on success. Until `onSubmit` settles,
 * Cancel, Escape, and a backdrop click do nothing: a caller that closes whichever
 * dialog is open when its request finishes, as `RecordSection` does, would
 * otherwise close a dialog the viewer opened in the meantime.
 *
 * @param props - The component props.
 * @returns The dialog element.
 */
export default function FormDialog<
    TInput extends FieldValues,
    TOutput extends FieldValues,
>(props: FormDialogProps<TInput, TOutput>) {
    const { open, onClose, onSubmit } = props
    const [pending, setPending] = useState(false)

    /**
     * Run the caller's submit handler, holding the dialog open until it settles.
     *
     * @param values - The validated form values.
     */
    const submit = async (values: TOutput) => {
        setPending(true)
        try {
            await onSubmit(values)
        } finally {
            setPending(false)
        }
    }

    return (
        <Dialog
            open={open}
            onClose={pending ? undefined : onClose}
            fullWidth
            maxWidth="sm"
        >
            <FormDialogBody {...props} onSubmit={submit} pending={pending} />
        </Dialog>
    )
}
