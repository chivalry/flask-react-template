/** @file Server state for the admin's account management. */

import { useQuery } from '@tanstack/react-query'

import { usersApi } from '../api/users'
import { useAuthStore } from '../store/auth'
import type { User } from '../types/users'
import { useResourceMutations } from './resources'

/** Cache key for the account list. */
const USERS_KEY = ['users'] as const

/**
 * Load every account; only admins may call the endpoint.
 *
 * @returns The query holding the accounts.
 */
export const useUsers = () => useQuery({ queryKey: USERS_KEY, queryFn: usersApi.list })

/**
 * Store a saved account as the signed-in user when it is that account.
 *
 * The update route answers with the fields `/me` returns, so the app bar shows an
 * edited email at once instead of after a reload, and the id is unchanged, so
 * `useSessionQueryCache` keeps the cache. Any other account, or a response that
 * lands after sign-out, leaves the store alone.
 *
 * @param user - The account as the server saved it.
 */
function syncSignedInUser(user: User) {
    const { user: signedIn, setUser } = useAuthStore.getState()
    if (signedIn?.id === user.id) setUser(user)
}

/**
 * Build the create and update mutations for accounts.
 *
 * The server has no delete route, so there is no `remove`, and a record section
 * given these mutations offers no Delete. A save also refreshes the audit log, so an
 * account's history beside the form shows the change, and an update to the signed-in
 * account replaces the auth store's copy of it.
 *
 * @returns The create and update mutations.
 */
export function useUserMutations() {
    const { create, update } = useResourceMutations(USERS_KEY, usersApi, {
        alsoInvalidate: [['audit-logs']],
        onUpdated: syncSignedInUser,
    })
    return { create, update }
}
