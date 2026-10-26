/** @file Validation and payload mapping for the account form. */

import { z } from 'zod'

import type { User, UserPayload } from '../types/users'

const PASSWORD_MESSAGE = 'Password must be at least 8 characters.'

/**
 * Build the account form's schema.
 *
 * A new account needs a password; an existing one keeps its password when the
 * field is left blank.
 *
 * @param isEdit - Whether the form edits an existing account.
 * @returns The schema.
 */
export function userFormSchema(isEdit: boolean) {
    return z.object({
        email: z.string().trim().email('Enter a valid email.'),
        password: z
            .string()
            .refine(
                (value) => (isEdit && value === '') || value.length >= 8,
                PASSWORD_MESSAGE,
            ),
        role: z.enum(['admin', 'user']),
        is_active: z.boolean(),
    })
}

/** The account form's values. */
type UserFormValues = z.infer<ReturnType<typeof userFormSchema>>

/**
 * Build the form's starting values from an account, or blanks for a new one.
 *
 * @param user - The account being edited, or null when creating.
 * @returns The default values.
 */
export function userFormDefaults(user: User | null): UserFormValues {
    return {
        email: user?.email ?? '',
        password: '',
        role: user?.role ?? 'user',
        is_active: user?.is_active ?? true,
    }
}

/**
 * Turn validated form values into the request body, omitting a blank password.
 *
 * @param values - The validated values.
 * @returns The payload.
 */
export function toUserPayload(values: UserFormValues): UserPayload {
    const payload: UserPayload = {
        email: values.email,
        role: values.role,
        is_active: values.is_active,
    }
    if (values.password) payload.password = values.password
    return payload
}
