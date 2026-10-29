/** @file How an account reads in lists and headings. */

import { describe, expect, it } from 'vitest'

import { describeUser } from '../../utils/users'
import { adminUser, plainUser } from './fixtures'

describe('describeUser', () => {
    it('names the role of an active account', () => {
        expect(describeUser(adminUser)).toBe('admin')
    })

    it('adds inactive for a deactivated account', () => {
        expect(describeUser({ ...plainUser, is_active: false })).toBe('user · inactive')
    })
})
