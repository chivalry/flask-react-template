/** @file Validation and payload mapping for the passkey nickname form. */

import { z } from 'zod'

import type { Passkey, PasskeyPayload } from '../types/auth'

/** The longest nickname the server accepts. */
const NICKNAME_MAX_LENGTH = 64

/** The nickname form, whose one field may be left blank. */
export const passkeyFormSchema = z.object({
    nickname: z
        .string()
        .trim()
        .max(NICKNAME_MAX_LENGTH, `Use ${NICKNAME_MAX_LENGTH} characters or fewer.`),
})

/** The nickname form's values. */
type PasskeyFormValues = z.infer<typeof passkeyFormSchema>

/**
 * Build the form's starting values from the passkey being renamed, or a blank.
 *
 * @param passkey - The passkey being renamed, or null when adding one.
 * @returns The default values.
 */
export function passkeyFormDefaults(passkey: Passkey | null): PasskeyFormValues {
    return { nickname: passkey?.nickname ?? '' }
}

/**
 * Turn validated form values into the request body; a blank nickname becomes null.
 *
 * @param values - The validated values.
 * @returns The payload.
 */
export function toPasskeyPayload(values: PasskeyFormValues): PasskeyPayload {
    return { nickname: values.nickname || null }
}
