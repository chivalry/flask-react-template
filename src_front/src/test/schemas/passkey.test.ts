/** @file The passkey nickname form's schema, starting values, and request body. */

import { describe, expect, it } from 'vitest'

import {
    passkeyFormDefaults,
    passkeyFormSchema,
    toPasskeyPayload,
} from '../../schemas/passkey'
import { laptopPasskey } from '../utils/fixtures'

describe('passkeyFormSchema', () => {
    it('trims the nickname before measuring it', () => {
        const padded = ` ${'x'.repeat(64)} `

        expect(passkeyFormSchema.parse({ nickname: '  Phone ' })).toEqual({
            nickname: 'Phone',
        })
        expect(passkeyFormSchema.parse({ nickname: padded })).toEqual({
            nickname: 'x'.repeat(64),
        })
    })

    it('refuses a nickname of 65 characters with its message', () => {
        const result = passkeyFormSchema.safeParse({ nickname: 'x'.repeat(65) })

        expect(result.success).toBe(false)
        expect(result.error?.issues.map((issue) => issue.message)).toEqual([
            'Use 64 characters or fewer.',
        ])
    })

    it('accepts a blank nickname', () => {
        expect(passkeyFormSchema.parse({ nickname: '' })).toEqual({ nickname: '' })
        expect(passkeyFormSchema.parse({ nickname: '   ' })).toEqual({ nickname: '' })
    })
})

describe('passkeyFormDefaults', () => {
    it('starts a rename from the passkey nickname', () => {
        expect(passkeyFormDefaults(laptopPasskey)).toEqual({ nickname: 'Laptop' })
    })

    it('starts blank for a passkey without a nickname', () => {
        expect(passkeyFormDefaults({ ...laptopPasskey, nickname: null })).toEqual({
            nickname: '',
        })
    })

    it('starts blank when adding a passkey', () => {
        expect(passkeyFormDefaults(null)).toEqual({ nickname: '' })
    })
})

describe('toPasskeyPayload', () => {
    it('sends a blank nickname as null, and a name as it is', () => {
        expect(toPasskeyPayload({ nickname: '' })).toEqual({ nickname: null })
        expect(toPasskeyPayload({ nickname: 'Phone' })).toEqual({ nickname: 'Phone' })
    })
})
