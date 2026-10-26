/** @file Signed-in accounts shared by the tests: one admin and one plain user. */

import type { AuthUser } from '../../types/auth'

const stamps = { created_at: '2026-10-10T00:00:00Z', updated_at: '2026-10-10T00:00:00Z' }

export const adminUser: AuthUser = {
    id: 1,
    uuid: 'user-uuid-1',
    email: 'admin@example.com',
    role: 'admin',
    has_password: true,
    is_active: true,
    ...stamps,
}

export const plainUser: AuthUser = {
    id: 2,
    uuid: 'user-uuid-2',
    email: 'user@example.com',
    role: 'user',
    has_password: true,
    is_active: true,
    ...stamps,
}
