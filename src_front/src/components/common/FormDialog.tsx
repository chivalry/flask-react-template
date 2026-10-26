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

/** Props accepted by {@link FormDialogButtons}. */
interface FormDialogButtonsProps {
    submitLabel: string
    submitting: boolean
    onClose: () => void
}

/**
 * Render the Cancel and submit buttons.
 *
 * @param props - The component props.
 * @returns The dialog actions element.
 */
function FormDialogButtons(props: FormDialogButtonsProps) {
    const { submitLabel, submitting, onClose } = props
    return (
        <DialogActions>
            <Button onClick={onClose}>Cancel</Button>
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
 * already cleared its editing state.
 *
 * @param props - The component props.
 * @returns The form element.
 */
function FormDialogBody<TInput extends FieldValues, TOutput extends FieldValues>(
    props: FormDialogProps<TInput, TOutput>,
) {
    const { open, title, submitLabel, onClose, onSubmit, children } = props
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
 * dialog open; the caller closes it on success.
 *
 * @param props - The component props.
 * @returns The dialog element.
 */
export default function FormDialog<
    TInput extends FieldValues,
    TOutput extends FieldValues,
>(props: FormDialogProps<TInput, TOutput>) {
    const { open, onClose } = props
    return (
        <Dialog open={open} onClose={onClose} fullWidth maxWidth="sm">
            <FormDialogBody {...props} />
        </Dialog>
    )
}
