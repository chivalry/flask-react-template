/** @file The account hooks load through the users API and build no delete. */

import { useQueryClient } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { usersApi } from '../../api/users'
import { useUserMutations, useUsers } from '../../hooks/users'
import { useAuthStore } from '../../store/auth'
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
        useAuthStore.setState({ user: null, isLoading: false })
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

    it('create sends the payload, then invalidates users and audit logs', async () => {
        vi.mocked(usersApi.create).mockResolvedValue(plainUser)
        const { result } = renderUserMutations()
        const invalidateQueries = vi.spyOn(result.current.client, 'invalidateQueries')

        await act(async () => {
            await result.current.mutations.create.mutateAsync(payload)
        })

        expect(usersApi.create).toHaveBeenCalledWith(payload)
        expect(invalidateQueries.mock.calls).toEqual([
            [{ queryKey: ['users'] }],
            [{ queryKey: ['audit-logs'] }],
        ])
    })

    it('update of the signed-in account replaces the stored user', async () => {
        const renamed = { ...adminUser, email: 'renamed@example.com' }
        useAuthStore.setState({ user: adminUser })
        vi.mocked(usersApi.update).mockResolvedValue(renamed)
        const { result } = renderUserMutations()

        await act(async () => {
            await result.current.mutations.update.mutateAsync({
                id: adminUser.id,
                payload,
            })
        })

        expect(useAuthStore.getState().user).toEqual(renamed)
    })

    it.each([
        { label: 'another account is signed in', signedIn: adminUser },
        { label: 'nobody is signed in', signedIn: null },
    ])('update leaves the stored user alone when $label', async ({ signedIn }) => {
        useAuthStore.setState({ user: signedIn })
        vi.mocked(usersApi.update).mockResolvedValue(plainUser)
        const { result } = renderUserMutations()

        await act(async () => {
            await result.current.mutations.update.mutateAsync({
                id: plainUser.id,
                payload,
            })
        })

        expect(useAuthStore.getState().user).toBe(signedIn)
    })
})
