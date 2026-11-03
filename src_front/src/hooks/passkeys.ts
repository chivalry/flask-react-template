/** @file Server state for the signed-in account's passkeys. */

import { useQuery } from '@tanstack/react-query'

import { passkeysApi } from '../api/passkeys'
import { useResourceMutations } from './resources'

/** Cache key for the signed-in account's passkeys. */
const PASSKEYS_KEY = ['passkeys'] as const

/**
 * Load the signed-in account's passkeys.
 *
 * @returns The query holding the passkeys.
 */
export const usePasskeys = () =>
    useQuery({ queryKey: PASSKEYS_KEY, queryFn: passkeysApi.list })

/**
 * Build the add, rename, and delete mutations for passkeys.
 *
 * Adding one runs the browser's prompt between its two requests.
 *
 * @returns The three mutations.
 */
export const usePasskeyMutations = () => useResourceMutations(PASSKEYS_KEY, passkeysApi)
