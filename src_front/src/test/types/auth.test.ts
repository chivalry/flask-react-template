import { describe, expect, it } from 'vitest'

import { isAdmin } from '../types/auth'

describe('isAdmin', () => {
    it('is true for the admin role', () => {
        expect(isAdmin('admin')).toBe(true)
    })

    it('is false for the user role', () => {
        expect(isAdmin('user')).toBe(false)
    })
})
