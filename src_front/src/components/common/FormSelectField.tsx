/** @file Single-choice dropdown bound to the enclosing react-hook-form context. */

import { MenuItem } from '@mui/material'

import FormTextField from './FormTextField'

/** One choice of a {@link FormSelectField}. */
interface SelectOption {
    value: string | number
    label: string
}

/** Props accepted by {@link FormSelectField}. */
interface FormSelectFieldProps {
    name: string
    label: string
    options: readonly SelectOption[]
    emptyLabel?: string
    disabled?: boolean
}

/**
 * Render a dropdown whose selection is stored in the form under `name`.
 *
 * @param props - The component props.
 * @returns The controlled select field.
 */
export default function FormSelectField(props: FormSelectFieldProps) {
    const { name, label, options, emptyLabel, disabled } = props
    return (
        <FormTextField name={name} label={label} select disabled={disabled}>
            {emptyLabel !== undefined && <MenuItem value="">{emptyLabel}</MenuItem>}
            {options.map((option) => (
                <MenuItem key={option.value} value={option.value}>
                    {option.label}
                </MenuItem>
            ))}
        </FormTextField>
    )
}
