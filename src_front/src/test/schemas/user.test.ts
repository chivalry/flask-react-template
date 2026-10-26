/** @file The account form's schema, starting values, and request body. */

import { describe, expect, it } from 'vitest'

import { toUserPayload, userFormDefaults, userFormSchema } from '../../schemas/user'
import type { User } from '../../types/users'
import { adminUser } from '../utils/fixtures'

const PASSWORD_MESSAGE = 'Password must be at least 8 characters.'

/** Form values for a plain account with the given password. */
const valuesWithPassword = (password: string) => ({
    email: 'new@example.com',
    password,
    role: 'user' as const,
    is_active: true,
})

/** The messages a failed parse reports, in order. */
const issueMessages = (result: { error?: { issues: { message: string }[] } }) =>
    result.error?.issues.map((issue) => issue.message)

describe('userFormSchema', () => {
    it('requires a password of at least 8 characters for a new account', () => {
        const schema = userFormSchema(false)

        for (const password of ['', 'short12']) {
            const result = schema.safeParse(valuesWithPassword(password))
            expect(result.success).toBe(false)
            expect(issueMessages(result)).toEqual([PASSWORD_MESSAGE])
        }
        expect(schema.safeParse(valuesWithPassword('longenough')).success).toBe(true)
    })

    it('accepts a blank password on edit but still rejects a short one', () => {
        const schema = userFormSchema(true)

        expect(schema.safeParse(valuesWithPassword('')).success).toBe(true)
        const short = schema.safeParse(valuesWithPassword('short12'))
        expect(short.success).toBe(false)
        expect(issueMessages(short)).toEqual([PASSWORD_MESSAGE])
    })

    it('trims the email before checking it', () => {
        const values = {
            ...valuesWithPassword('longenough'),
            email: '  new@example.com ',
        }

        expect(userFormSchema(false).parse(values).email).toBe('new@example.com')
        const blank = userFormSchema(false).safeParse({ ...values, email: '   ' })
        expect(issueMessages(blank)).toEqual(['Enter a valid email.'])
    })
})

describe('userFormDefaults', () => {
    it('starts a new account blank, as an active user', () => {
        expect(userFormDefaults(null)).toEqual({
            email: '',
            password: '',
            role: 'user',
            is_active: true,
        })
    })

    it('starts an edit from the account, with the password blank', () => {
        const inactiveAdmin: User = { ...adminUser, is_active: false }

        expect(userFormDefaults(inactiveAdmin)).toEqual({
            email: adminUser.email,
            password: '',
            role: 'admin',
            is_active: false,
        })
    })
})

describe('toUserPayload', () => {
    it('omits a blank password', () => {
        const payload = toUserPayload(valuesWithPassword(''))

        expect(payload).toEqual({
            email: 'new@example.com',
            role: 'user',
            is_active: true,
        })
        expect(payload).not.toHaveProperty('password')
    })

    it('includes a filled password', () => {
        expect(toUserPayload(valuesWithPassword('longenough'))).toEqual({
            email: 'new@example.com',
            password: 'longenough',
            role: 'user',
            is_active: true,
        })
    })
})
