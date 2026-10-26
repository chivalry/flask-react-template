/** @file The account endpoints target `/v1/users` through the shared client. */

import { beforeEach, describe, expect, it, vi } from 'vitest'

import client, { fetchAll } from '../../api/client'
import { usersApi } from '../../api/users'
import type { UserPayload } from '../../types/users'
import { adminUser, plainUser } from '../utils/fixtures'

vi.mock('../../api/client', () => ({ default: { put: vi.fn() }, fetchAll: vi.fn() }))

const payload: UserPayload = { email: plainUser.email, role: 'admin', is_active: false }

describe('usersApi', () => {
    beforeEach(() => {
        vi.resetAllMocks()
    })

    it('lists every page of /v1/users', async () => {
        vi.mocked(fetchAll).mockResolvedValue([adminUser, plainUser])

        await expect(usersApi.list()).resolves.toEqual([adminUser, plainUser])

        expect(fetchAll).toHaveBeenCalledWith('/v1/users')
    })

    it('puts an update to the account path', async () => {
        vi.mocked(client.put).mockResolvedValue({ data: plainUser })

        await expect(usersApi.update(3, payload)).resolves.toBe(plainUser)

        expect(client.put).toHaveBeenCalledWith('/v1/users/3', payload)
    })
})
