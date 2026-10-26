/** @file Server state for the admin's account management. */

import { useQuery } from '@tanstack/react-query'

import { usersApi } from '../api/users'
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
 * Build the create and update mutations for accounts.
 *
 * The server has no delete route, so there is no `remove`, and a record section
 * given these mutations offers no Delete.
 *
 * @returns The create and update mutations.
 */
export function useUserMutations() {
    const { create, update } = useResourceMutations(USERS_KEY, usersApi)
    return { create, update }
}
