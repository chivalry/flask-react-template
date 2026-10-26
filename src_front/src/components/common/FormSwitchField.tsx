/** @file On/off switch bound to the enclosing react-hook-form context. */

import { FormControlLabel, Switch } from '@mui/material'
import { Controller, useFormContext } from 'react-hook-form'

/** Props accepted by {@link FormSwitchField}. */
interface FormSwitchFieldProps {
    name: string
    label: string
    disabled?: boolean
}

/**
 * Render a labelled switch whose boolean lives in the form under `name`.
 *
 * @param props - The component props.
 * @returns The controlled switch.
 */
export default function FormSwitchField(props: FormSwitchFieldProps) {
    const { name, label, disabled } = props
    const { control } = useFormContext()
    return (
        <Controller
            name={name}
            control={control}
            render={({ field }) => (
                <FormControlLabel
                    label={label}
                    disabled={disabled}
                    control={
                        <Switch
                            checked={Boolean(field.value)}
                            onChange={(event) => field.onChange(event.target.checked)}
                            onBlur={field.onBlur}
                            inputRef={field.ref}
                        />
                    }
                />
            )}
        />
    )
}
