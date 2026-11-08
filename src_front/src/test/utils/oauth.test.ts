/** @file The links that start a provider sign-in, and the text for each failure code. */

import { describe, expect, it } from 'vitest'

import { linkUrl, oauthErrorMessage, startUrl } from '../../utils/oauth'

/** The fallback for a code the build does not know. */
const FALLBACK = 'Sign-in failed. Please try again.'

/** Every code the provider routes redirect with, and the text each one shows. */
const MESSAGES: [string, string][] = [
    ['unknown_provider', 'That sign-in provider is not available.'],
    ['cancelled', 'Sign-in was cancelled.'],
    ['invalid_state', 'That sign-in could not be verified. Please try again.'],
    ['expired', 'That sign-in took too long. Please try again.'],
    ['exchange_failed', 'The sign-in provider could not finish. Please try again.'],
    ['invalid_token', 'The sign-in could not be verified. Please try again.'],
    [
        'email_required',
        'The sign-in provider did not share an email address, which every account here ' +
            'needs. Share it and try again, or sign in another way.',
    ],
    ['email_unverified', 'Verify your email with the sign-in provider, then try again.'],
    [
        'link_required',
        'That email already has an account. Sign in, then link it from Account.',
    ],
    ['already_linked', 'That account is already linked to a sign-in provider.'],
    ['account_inactive', 'Account is inactive.'],
]

describe('startUrl', () => {
    it('starts the provider sign-in under /api, with no query without next', () => {
        expect(startUrl('google')).toBe('/api/v1/auth/oauth/google/start')
    })

    it('carries next as one encoded parameter, ? and # included', () => {
        expect(startUrl('google', '/widgets/12?tab=notes#latest')).toBe(
            '/api/v1/auth/oauth/google/start?next=%2Fwidgets%2F12%3Ftab%3Dnotes%23latest',
        )
    })

    it('encodes the provider name as one path segment', () => {
        expect(startUrl('a/b?c')).toBe('/api/v1/auth/oauth/a%2Fb%3Fc/start')
    })
})

describe('linkUrl', () => {
    it('returns to the Account page and asks the server to link', () => {
        expect(linkUrl('google')).toBe(
            '/api/v1/auth/oauth/google/start?next=%2Faccount&link=1',
        )
    })
})

describe('oauthErrorMessage', () => {
    it('knows all eleven codes', () => {
        expect(MESSAGES).toHaveLength(11)
    })

    it.each(MESSAGES)('gives %s its own message', (code, message) => {
        expect(oauthErrorMessage(code)).toBe(message)
    })

    it.each([null, ''])('gives no message for %j', (code) => {
        expect(oauthErrorMessage(code)).toBeNull()
    })

    it.each(['nope', '__proto__', 'constructor'])(
        'falls back for the unknown code %s, inherited names included',
        (code) => {
            expect(oauthErrorMessage(code)).toBe(FALLBACK)
        },
    )
})
