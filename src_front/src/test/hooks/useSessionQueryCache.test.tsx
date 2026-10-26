/** @file Account transitions cannot reuse cached or outstanding server queries. */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook } from '@testing-library/react'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it } from 'vitest'

import { useSessionQueryCache } from '../../hooks/useSessionQueryCache'
import { useAuthStore } from '../../store/auth'
import { adminUser, plainUser } from '../utils/fixtures'

/** Mount the session listener against the supplied real query cache. */
function mountSessionListener(client: QueryClient) {
    return renderHook(() => useSessionQueryCache(), {
        wrapper: ({ children }: { children: ReactNode }) => (
            <QueryClientProvider client={client}>{children}</QueryClientProvider>
        ),
    })
}

describe('useSessionQueryCache', () => {
    beforeEach(() => useAuthStore.setState({ user: adminUser, isLoading: false }))

    it('drops account data synchronously on logout and on a different login', () => {
        const client = new QueryClient()
        mountSessionListener(client)
        client.setQueryData(['users'], [adminUser])
        act(() => useAuthStore.getState().clearUser())
        expect(client.getQueryCache().getAll()).toHaveLength(0)
        client.setQueryData(['people'], ['anonymous stale response'])
        act(() => useAuthStore.getState().setUser(plainUser))
        expect(client.getQueryCache().getAll()).toHaveLength(0)
    })

    it('cancels an old request whose query function ignores cancellation', async () => {
        const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
        mountSessionListener(client)
        let resolveOldRequest: (value: string) => void = () => undefined
        const oldRequest = client
            .fetchQuery({
                queryKey: ['people'],
                queryFn: () =>
                    new Promise<string>((resolve) => {
                        resolveOldRequest = resolve
                    }),
            })
            .catch(() => undefined)
        act(() => useAuthStore.getState().setUser(plainUser))
        await client.fetchQuery({
            queryKey: ['people'],
            queryFn: () => 'new account data',
        })
        resolveOldRequest('old admin data')
        expect(await oldRequest).toBeUndefined()
        expect(client.getQueryData(['people'])).toBe('new account data')
        client.clear()
    })

    it('preserves cache for the same account and unsubscribes on unmount', () => {
        const client = new QueryClient()
        const listener = mountSessionListener(client)
        client.setQueryData(['people'], ['Ada'])
        act(() =>
            useAuthStore
                .getState()
                .setUser({ ...adminUser, email: 'updated@example.com' }),
        )
        expect(client.getQueryData(['people'])).toEqual(['Ada'])
        listener.unmount()
        act(() => useAuthStore.getState().clearUser())
        expect(client.getQueryData(['people'])).toEqual(['Ada'])
        client.clear()
    })
})
