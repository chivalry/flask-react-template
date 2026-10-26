/** @file Text input bound to the enclosing react-hook-form context. */

import { TextField } from '@mui/material'
import type { TextFieldProps } from '@mui/material'
import { Controller, useFormContext } from 'react-hook-form'

/** Props accepted by {@link FormTextField}: the field name plus any TextField prop. */
type FormTextFieldProps = Omit<
    TextFieldProps,
    'name' | 'value' | 'onChange' | 'onBlur' | 'error' | 'inputRef'
> & { name: string }

/**
 * Render a text field whose value and validation message come from the form.
 *
 * @param props - The component props.
 * @returns The controlled text field.
 */
export default function FormTextField(props: FormTextFieldProps) {
    const { name, helperText, ...rest } = props
    const { control } = useFormContext()
    return (
        <Controller
            name={name}
            control={control}
            render={({ field, fieldState }) => (
                <TextField
                    fullWidth
                    margin="dense"
                    {...rest}
                    name={field.name}
                    value={field.value ?? ''}
                    onChange={field.onChange}
                    onBlur={field.onBlur}
                    inputRef={field.ref}
                    error={Boolean(fieldState.error)}
                    helperText={fieldState.error?.message ?? helperText}
                />
            )}
        />
    )
}
