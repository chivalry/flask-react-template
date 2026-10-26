/** @file The account hooks load through the users API and build no delete. */

import { useQueryClient } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { usersApi } from '../../api/users'
import { useUserMutations, useUsers } from '../../hooks/users'
import type { UserPayload } from '../../types/users'
import { adminUser, plainUser } from '../utils/fixtures'
import Providers from '../utils/Providers'

vi.mock('../../api/users')

const payload: UserPayload = {
    email: 'new@example.com',
    password: 'longenough',
    role: 'user',
    is_active: true,
}

/** Render the account mutations beside the query client they report to. */
const renderUserMutations = () =>
    renderHook(() => ({ client: useQueryClient(), mutations: useUserMutations() }), {
        wrapper: Providers,
    })

describe('account hooks', () => {
    beforeEach(() => {
        vi.clearAllMocks()
    })

    it('useUsers loads every account through usersApi.list', async () => {
        vi.mocked(usersApi.list).mockResolvedValue([adminUser, plainUser])

        const { result } = renderHook(() => useUsers(), { wrapper: Providers })

        await waitFor(() => expect(result.current.data).toEqual([adminUser, plainUser]))
        expect(usersApi.list).toHaveBeenCalledTimes(1)
    })

    it('useUserMutations offers create and update but no remove', () => {
        const { result } = renderUserMutations()

        expect(Object.keys(result.current.mutations)).toEqual(['create', 'update'])
    })

    it('create sends the payload, then invalidates the account list', async () => {
        vi.mocked(usersApi.create).mockResolvedValue(plainUser)
        const { result } = renderUserMutations()
        const invalidateQueries = vi.spyOn(result.current.client, 'invalidateQueries')

        await act(async () => {
            await result.current.mutations.create.mutateAsync(payload)
        })

        expect(usersApi.create).toHaveBeenCalledWith(payload)
        expect(invalidateQueries.mock.calls).toEqual([[{ queryKey: ['users'] }]])
    })
})
