/** @file Mutations invalidate every key, and a delete first drops the detail query. */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook } from '@testing-library/react'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { ResourceApi } from '../../api/resources'
import { useResourceMutations } from '../../hooks/resources'

/** A record of the stand-in resource. */
interface Thing {
    id: number
    name: string
}

/** The body the stand-in resource accepts. */
interface ThingPayload {
    name: string
}

/** The stand-in resource's API. */
type ThingApi = ResourceApi<Thing, ThingPayload>

/** The mutations the hook builds for the stand-in resource. */
type ThingMutations = ReturnType<typeof useResourceMutations<Thing, ThingPayload>>

const thing: Thing = { id: 8, name: 'Widget' }
const payload: ThingPayload = { name: 'Widget' }

/** The calls `invalidateQueries` receives: the resource's key, then the extra one. */
const BOTH_KEYS = [[{ queryKey: ['things'] }], [{ queryKey: ['other'] }]]

const api = {
    list: vi.fn<ThingApi['list']>(),
    create: vi.fn<ThingApi['create']>(),
    update: vi.fn<ThingApi['update']>(),
    remove: vi.fn<ThingApi['remove']>(),
}

let queryClient: QueryClient

/** Supply the test's query client to the hook. */
function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
}

/** Spy on the cache calls the mutations make, keeping their real behavior. */
function spyOnCache() {
    return {
        invalidateQueries: vi.spyOn(queryClient, 'invalidateQueries'),
        removeQueries: vi.spyOn(queryClient, 'removeQueries'),
    }
}

/** Render the mutations for `['things']`, with `['other']` as an extra key. */
function renderMutations() {
    return renderHook(() => useResourceMutations(['things'], api, [['other']]), {
        wrapper: Wrapper,
    })
}

/** Run one mutation, then check that it invalidated both keys and dropped no query. */
async function expectMutationToInvalidateBothKeys(
    run: (mutations: ThingMutations) => Promise<unknown>,
) {
    const { invalidateQueries, removeQueries } = spyOnCache()
    const { result } = renderMutations()

    await act(async () => {
        await run(result.current)
    })

    expect(invalidateQueries.mock.calls).toEqual(BOTH_KEYS)
    expect(removeQueries).not.toHaveBeenCalled()
}

describe('useResourceMutations', () => {
    beforeEach(() => {
        vi.resetAllMocks()
        api.create.mockResolvedValue(thing)
        api.update.mockResolvedValue(thing)
        api.remove.mockResolvedValue(undefined)
        queryClient = new QueryClient({
            defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
        })
    })

    it('create sends the payload, then invalidates both keys', async () => {
        await expectMutationToInvalidateBothKeys((mutations) =>
            mutations.create.mutateAsync(payload),
        )

        expect(api.create).toHaveBeenCalledWith(payload)
    })

    it('update sends the id and payload, then invalidates both keys', async () => {
        await expectMutationToInvalidateBothKeys((mutations) =>
            mutations.update.mutateAsync({ id: 8, payload }),
        )

        expect(api.update).toHaveBeenCalledWith(8, payload)
    })

    it('remove drops the detail query before invalidating both keys', async () => {
        queryClient.setQueryData(['things'], [thing])
        queryClient.setQueryData(['things', 8], thing)
        const { invalidateQueries, removeQueries } = spyOnCache()
        const { result } = renderMutations()

        await act(async () => {
            await result.current.remove.mutateAsync(8)
        })

        expect(api.remove).toHaveBeenCalledWith(8)
        expect(removeQueries.mock.calls).toEqual([[{ queryKey: ['things', 8] }]])
        expect(invalidateQueries.mock.calls).toEqual(BOTH_KEYS)
        const [removedAt] = removeQueries.mock.invocationCallOrder
        const firstInvalidatedAt = Math.min(...invalidateQueries.mock.invocationCallOrder)
        expect(removedAt).toBeLessThan(firstInvalidatedAt)
        expect(queryClient.getQueryData(['things', 8])).toBeUndefined()
        expect(queryClient.getQueryData(['things'])).toEqual([thing])
        expect(queryClient.getQueryState(['things'])?.isInvalidated).toBe(true)
    })

    it('invalidates only the resource key when given no extra keys', async () => {
        const { invalidateQueries } = spyOnCache()
        const { result } = renderHook(() => useResourceMutations(['things'], api), {
            wrapper: Wrapper,
        })

        await act(async () => {
            await result.current.create.mutateAsync(payload)
        })

        expect(invalidateQueries.mock.calls).toEqual([[{ queryKey: ['things'] }]])
    })
})
