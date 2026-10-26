/** @file Remove server state synchronously when the signed-in account changes. */

import { useQueryClient } from '@tanstack/react-query'
import { useEffect } from 'react'

import { useAuthStore } from '../store/auth'

/**
 * Cancel outstanding queries and discard cached data before a new account renders.
 *
 * Subscribe directly to the store so clearing happens during the account change,
 * before the next account's components can observe the previous account's cache.
 * Updating the same account's profile preserves its cached server state.
 */
export function useSessionQueryCache() {
    const client = useQueryClient()
    useEffect(
        () =>
            useAuthStore.subscribe((state, previous) => {
                if (state.user?.id !== previous.user?.id) client.clear()
            }),
        [client],
    )
}
