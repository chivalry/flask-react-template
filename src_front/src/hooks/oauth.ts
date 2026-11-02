/** @file Server state for the accounts linked through sign-in providers. */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { listLinkedAccounts, unlinkAccount } from '../api/oauth'

/** Cache key for the signed-in account's links. */
const LINKED_ACCOUNTS_KEY = ['linked-accounts'] as const

/**
 * Load the signed-in account's linked providers.
 *
 * @returns The query holding the links.
 */
export const useLinkedAccounts = () =>
    useQuery({ queryKey: LINKED_ACCOUNTS_KEY, queryFn: listLinkedAccounts })

/**
 * Build the mutation that removes a link, by provider name.
 *
 * @returns The mutation, which refreshes the links on success.
 */
export function useUnlinkAccount() {
    const queryClient = useQueryClient()
    return useMutation({
        mutationFn: unlinkAccount,
        onSuccess: () => {
            void queryClient.invalidateQueries({ queryKey: LINKED_ACCOUNTS_KEY })
        },
    })
}
