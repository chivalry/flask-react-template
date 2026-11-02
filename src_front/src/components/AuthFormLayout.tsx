/** @file Shared shell and field control for the sign-in and register forms. */

import { Alert, Box, Button, Container, TextField, Typography } from '@mui/material'
import type { FormEventHandler, ReactNode } from 'react'
import type { UseFormRegisterReturn } from 'react-hook-form'

/** Props accepted by {@link AuthTextField}. */
interface AuthTextFieldProps {
    registration: UseFormRegisterReturn
    label: string
    type: string
    error?: string
    autoComplete?: string
}

/**
 * Render one labelled auth field wired to react-hook-form.
 *
 * @param props - The component props.
 * @param props.registration - The result of the form's `register` call.
 * @param props.label - The field's visible label.
 * @param props.type - The underlying input type.
 * @param props.error - Validation message to show, or undefined when valid.
 * @param props.autoComplete - The browser's autofill hint, if any.
 * @returns The text field element.
 */
export function AuthTextField({
    registration,
    label,
    type,
    error,
    autoComplete,
}: AuthTextFieldProps) {
    return (
        <TextField
            {...registration}
            label={label}
            type={type}
            autoComplete={autoComplete}
            fullWidth
            margin="normal"
            error={Boolean(error)}
            helperText={error}
        />
    )
}

/** Props accepted by {@link AuthFormLayout}. */
interface AuthFormLayoutProps {
    children: ReactNode
    title: string
    apiError: string | null
    isSubmitting: boolean
    submitLabel: string
    secondary?: ReactNode
    footer: ReactNode
    onSubmit: FormEventHandler<HTMLFormElement>
}

/**
 * Render the page shell both auth forms share.
 *
 * @param props - The component props.
 * @param props.children - The form's field controls.
 * @param props.title - Heading text above the form.
 * @param props.apiError - Server error to display, or null.
 * @param props.isSubmitting - Whether a submit is in flight.
 * @param props.submitLabel - Text for the submit button.
 * @param props.secondary - Other ways to sign in, shown beneath the submit button.
 * @param props.footer - Link text shown beneath the submit button.
 * @param props.onSubmit - The form's submit handler.
 * @returns The auth page element.
 */
export default function AuthFormLayout({
    children,
    title,
    apiError,
    isSubmitting,
    submitLabel,
    secondary,
    footer,
    onSubmit,
}: AuthFormLayoutProps) {
    return (
        <Container maxWidth="xs" sx={{ mt: 8 }}>
            <Typography variant="h5" component="h1" gutterBottom>
                {title}
            </Typography>
            {apiError && (
                <Alert severity="error" sx={{ mb: 2 }}>
                    {apiError}
                </Alert>
            )}
            <Box component="form" onSubmit={onSubmit} noValidate>
                {children}
                <Button
                    type="submit"
                    variant="contained"
                    fullWidth
                    sx={{ mt: 2 }}
                    disabled={isSubmitting}
                >
                    {submitLabel}
                </Button>
                {secondary}
                <Typography variant="body2" sx={{ mt: 2 }}>
                    {footer}
                </Typography>
            </Box>
        </Container>
    )
}
