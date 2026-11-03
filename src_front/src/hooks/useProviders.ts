/** @file The sign-in providers the server has enabled. */

import { useEffect, useState } from 'react'

import { listProviders } from '../api/oauth'
import type { OAuthProviderInfo } from '../types/auth'

/**
 * Load the enabled providers once.
 *
 * The list goes in local state rather than a query, as in `EnvironmentBadge`:
 * `useSessionQueryCache` clears every query when the account changes, which would
 * cancel the fetch during sign-in. A failure leaves the list empty, so the sign-in
 * pages fall back to the password form.
 *
 * @returns The providers; empty until they load, and after a failure.
 */
export function useProviders(): OAuthProviderInfo[] {
    const [providers, setProviders] = useState<OAuthProviderInfo[]>([])

    useEffect(() => {
        void listProviders()
            .then(setProviders)
            .catch(() => undefined)
    }, [])

    return providers
}
