/** @file The passkey hooks load through the passkey API and refresh after each change. */

import { useQueryClient } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { passkeysApi } from '../../api/passkeys'
import { usePasskeyMutations, usePasskeys } from '../../hooks/passkeys'
import type { PasskeyPayload } from '../../types/auth'
import { laptopPasskey } from '../utils/fixtures'
import Providers from '../utils/Providers'

vi.mock('../../api/passkeys')

/** The mutations the hook builds. */
type PasskeyMutations = ReturnType<typeof usePasskeyMutations>

const payload: PasskeyPayload = { nickname: 'Laptop' }

/**
 * Run one passkey mutation beside the query client it reports to.
 *
 * @param run - Makes the mutation's call.
 * @returns The calls `invalidateQueries` received.
 */
async function invalidationsAfter(
    run: (mutations: PasskeyMutations) => Promise<unknown>,
) {
    const { result } = renderHook(
        () => ({ client: useQueryClient(), mutations: usePasskeyMutations() }),
        { wrapper: Providers },
    )
    const invalidateQueries = vi.spyOn(result.current.client, 'invalidateQueries')

    await act(async () => {
        await run(result.current.mutations)
    })

    return invalidateQueries.mock.calls
}

describe('passkey hooks', () => {
    beforeEach(() => {
        vi.clearAllMocks()
    })

    it('usePasskeys loads the passkeys through passkeysApi.list', async () => {
        vi.mocked(passkeysApi.list).mockResolvedValue([laptopPasskey])

        const { result } = renderHook(() => usePasskeys(), { wrapper: Providers })

        await waitFor(() => expect(result.current.data).toEqual([laptopPasskey]))
        expect(passkeysApi.list).toHaveBeenCalledTimes(1)
    })

    it('create calls passkeysApi.create, then invalidates the passkeys', async () => {
        vi.mocked(passkeysApi.create).mockResolvedValue(laptopPasskey)

        const calls = await invalidationsAfter((mutations) =>
            mutations.create.mutateAsync(payload),
        )

        expect(passkeysApi.create).toHaveBeenCalledExactlyOnceWith(payload)
        expect(calls).toEqual([[{ queryKey: ['passkeys'] }]])
    })

    it('update calls passkeysApi.update, then invalidates the passkeys', async () => {
        vi.mocked(passkeysApi.update).mockResolvedValue(laptopPasskey)

        const calls = await invalidationsAfter((mutations) =>
            mutations.update.mutateAsync({ id: laptopPasskey.id, payload }),
        )

        expect(passkeysApi.update).toHaveBeenCalledExactlyOnceWith(3, payload)
        expect(calls).toEqual([[{ queryKey: ['passkeys'] }]])
    })

    it('remove calls passkeysApi.remove, then invalidates the passkeys', async () => {
        vi.mocked(passkeysApi.remove).mockResolvedValue(undefined)

        const calls = await invalidationsAfter((mutations) =>
            mutations.remove.mutateAsync(laptopPasskey.id),
        )

        expect(passkeysApi.remove).toHaveBeenCalledExactlyOnceWith(3)
        expect(calls).toEqual([[{ queryKey: ['passkeys'] }]])
    })
})
