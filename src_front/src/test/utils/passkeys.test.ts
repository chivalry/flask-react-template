/** @file Cancelled prompts, failed setups, and how a passkey is named and described. */

import { describe, expect, it } from 'vitest'

import { formatLocalDateTime } from '../../utils/dates'
import {
    describePasskeyUse,
    isCancelledCeremony,
    passkeyName,
    registrationFailure,
} from '../../utils/passkeys'
import { laptopPasskey } from './fixtures'
import { ceremonyError } from './webauthn'

/** A plain `Error` that only borrows the browser's name for a dismissal. */
const plainNotAllowed = () => {
    const err = new Error('The browser refused.')
    err.name = 'NotAllowedError'
    return err
}

describe('isCancelledCeremony', () => {
    it.each([
        ['an aborted ceremony', ceremonyError('ERROR_CEREMONY_ABORTED', 'AbortError')],
        [
            'a dismissed or timed-out prompt',
            ceremonyError('ERROR_PASSTHROUGH_SEE_CAUSE_PROPERTY', 'NotAllowedError'),
        ],
    ])('is true for %s', (_label, err) => {
        expect(isCancelledCeremony(err)).toBe(true)
    })

    it.each([
        ['another code', ceremonyError('ERROR_INVALID_DOMAIN', 'SecurityError')],
        ['a plain Error named NotAllowedError', plainNotAllowed()],
        ['a string', 'NotAllowedError'],
    ])('is false for %s', (_label, err) => {
        expect(isCancelledCeremony(err)).toBe(false)
    })
})

describe('registrationFailure', () => {
    it('says a dismissed prompt was cancelled', () => {
        const err = ceremonyError(
            'ERROR_PASSTHROUGH_SEE_CAUSE_PROPERTY',
            'NotAllowedError',
        )

        expect(registrationFailure(err).message).toBe('Passkey setup was cancelled.')
    })

    it('says the device already holds a passkey for the account', () => {
        const err = ceremonyError(
            'ERROR_AUTHENTICATOR_PREVIOUSLY_REGISTERED',
            'InvalidStateError',
        )

        expect(registrationFailure(err).message).toBe(
            'This device already holds a passkey for your account.',
        )
    })

    it('passes another Error through', () => {
        const err = ceremonyError('ERROR_INVALID_DOMAIN', 'SecurityError')

        expect(registrationFailure(err)).toBe(err)
    })

    it('wraps a value that is not an Error', () => {
        const failure = registrationFailure('broken')

        expect(failure).toBeInstanceOf(Error)
        expect(failure.message).toBe('Passkey setup failed.')
    })
})

describe('passkeyName', () => {
    it('names a passkey by its nickname', () => {
        expect(passkeyName(laptopPasskey)).toBe('Laptop')
    })

    it('stands in for a missing nickname', () => {
        expect(passkeyName({ ...laptopPasskey, nickname: null })).toBe('Unnamed passkey')
    })
})

describe('describePasskeyUse', () => {
    it('says when the passkey was added and last used, in local time', () => {
        const added = formatLocalDateTime(laptopPasskey.created_at)
        const used = formatLocalDateTime(laptopPasskey.last_used_at!)

        expect(describePasskeyUse(laptopPasskey)).toBe(
            `Added ${added}, last used ${used}`,
        )
    })

    it('ends with never used for a passkey that has not signed in', () => {
        const unused = { ...laptopPasskey, last_used_at: null }

        expect(describePasskeyUse(unused)).toBe(
            `Added ${formatLocalDateTime(laptopPasskey.created_at)}, never used`,
        )
    })
})
