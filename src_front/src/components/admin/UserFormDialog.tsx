/** @file Dialog for creating or editing an account. */

import { useMemo } from 'react'

import { toUserPayload, userFormDefaults, userFormSchema } from '../../schemas/user'
import { useAuthStore } from '../../store/auth'
import type { User, UserPayload } from '../../types/users'
import FormDialog from '../common/FormDialog'
import FormSelectField from '../common/FormSelectField'
import FormSwitchField from '../common/FormSwitchField'
import FormTextField from '../common/FormTextField'
import type { RecordDialogProps } from '../common/RecordSection'

const ROLE_OPTIONS = [
    { value: 'admin', label: 'Admin' },
    { value: 'user', label: 'User' },
]

/**
 * Say what a blank password field does to the account being edited.
 *
 * An account a sign-in provider created has no password, so leaving the field
 * blank keeps it without one rather than keeping a current password.
 *
 * @param item - The account being edited, or null when creating.
 * @returns The helper text, or undefined for a new account, which needs a password.
 */
function passwordHelperText(item: User | null): string | undefined {
    if (!item) return undefined
    return item.has_password
        ? 'Leave blank to keep the current password.'
        : 'This account has no password; leave blank to keep it that way.'
}

/**
 * Render the account form in a dialog.
 *
 * An admin cannot change their own role or deactivate themself, so those
 * controls are disabled on their own account.
 *
 * @param props - The dialog props from the owning record section.
 * @returns The dialog element.
 */
export default function UserFormDialog(props: RecordDialogProps<User, UserPayload>) {
    const { open, item, onClose, onSubmit } = props
    const me = useAuthStore((s) => s.user)
    const isSelf = item !== null && me !== null && item.id === me.id
    const schema = useMemo(() => userFormSchema(item !== null), [item])
    return (
        <FormDialog
            open={open}
            title={item ? 'Edit user' : 'New user'}
            schema={schema}
            defaultValues={userFormDefaults(item)}
            onClose={onClose}
            onSubmit={(values) => onSubmit(toUserPayload(values))}
        >
            <FormTextField name="email" label="Email" type="email" autoFocus />
            <FormTextField
                name="password"
                label={item ? 'New password' : 'Password'}
                type="password"
                helperText={passwordHelperText(item)}
            />
            <FormSelectField
                name="role"
                label="Role"
                options={ROLE_OPTIONS}
                disabled={isSelf}
            />
            <FormSwitchField name="is_active" label="Active" disabled={isSelf} />
        </FormDialog>
    )
}
