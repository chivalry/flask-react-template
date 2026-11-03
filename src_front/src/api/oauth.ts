/** @file Sign-in providers and the accounts linked through them. */

import type { LinkedAccount, OAuthProviderInfo } from '../types/auth'
import client from './client'

/** Where the provider endpoints live, relative to the API base. */
const OAUTH_URL = '/v1/auth/oauth'

/**
 * Fetch the sign-in providers the server has enabled.
 *
 * @returns Each provider's name and label; empty when none is enabled.
 */
export async function listProviders(): Promise<OAuthProviderInfo[]> {
    const { data } = await client.get<OAuthProviderInfo[]>(`${OAUTH_URL}/providers`)
    return data
}

/**
 * Fetch the signed-in account's linked providers.
 *
 * @returns The links, in provider order.
 */
export async function listLinkedAccounts(): Promise<LinkedAccount[]> {
    const { data } = await client.get<LinkedAccount[]>(`${OAUTH_URL}/accounts`)
    return data
}

/**
 * Remove the signed-in account's link to a provider.
 *
 * @param provider - The provider's name.
 * @returns A promise that settles when the link is gone; it rejects with the server's
 *   message when the provider is the account's last way to sign in.
 */
export async function unlinkAccount(provider: string): Promise<void> {
    await client.delete(`${OAUTH_URL}/accounts/${encodeURIComponent(provider)}`)
}
