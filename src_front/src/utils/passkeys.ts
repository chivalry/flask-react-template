/** @file Telling a cancelled passkey prompt from a failure, and describing a passkey. */

import { WebAuthnError } from '@simplewebauthn/browser'

import type { Passkey } from '../types/auth'
import { formatLocalDateTime } from './dates'

/**
 * Tell whether a passkey prompt ended because the visitor dismissed it, it timed out, or
 * a newer ceremony replaced it.
 *
 * The browser reports a dismissal and a timeout alike, as `NotAllowedError`, so neither
 * is shown as a failure.
 *
 * @param err - What the ceremony rejected with.
 * @returns True for a cancellation.
 */
export function isCancelledCeremony(err: unknown): boolean {
    return (
        err instanceof WebAuthnError &&
        (err.code === 'ERROR_CEREMONY_ABORTED' || err.name === 'NotAllowedError')
    )
}

/**
 * Explain why the browser created no passkey.
 *
 * @param err - What `startRegistration` rejected with.
 * @returns The error to show in the dialog.
 */
export function registrationFailure(err: unknown): Error {
    if (isCancelledCeremony(err)) return new Error('Passkey setup was cancelled.')
    if (
        err instanceof WebAuthnError &&
        err.code === 'ERROR_AUTHENTICATOR_PREVIOUSLY_REGISTERED'
    ) {
        return new Error('This device already holds a passkey for your account.')
    }
    return err instanceof Error ? err : new Error('Passkey setup failed.')
}

/**
 * Name a passkey in its list.
 *
 * @param passkey - The passkey.
 * @returns Its nickname, or a stand-in without one.
 */
export function passkeyName(passkey: Passkey): string {
    return passkey.nickname ?? 'Unnamed passkey'
}

/**
 * Say when a passkey was added and last signed in.
 *
 * @param passkey - The passkey.
 * @returns For example `Added Oct 9, 2026, 5:00 PM, never used`.
 */
export function describePasskeyUse(passkey: Passkey): string {
    const added = `Added ${formatLocalDateTime(passkey.created_at)}`
    const used = passkey.last_used_at
        ? `last used ${formatLocalDateTime(passkey.last_used_at)}`
        : 'never used'
    return `${added}, ${used}`
}
