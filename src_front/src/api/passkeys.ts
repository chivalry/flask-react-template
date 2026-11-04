/** @file Passkeys: the ceremonies' endpoints, and the signed-in account's passkeys. */

import {
    startRegistration,
    type AuthenticationResponseJSON,
    type PublicKeyCredentialCreationOptionsJSON,
    type PublicKeyCredentialRequestOptionsJSON,
    type RegistrationResponseJSON,
} from '@simplewebauthn/browser'

import type { AuthUser, Passkey, PasskeyPayload } from '../types/auth'
import { registrationFailure } from '../utils/passkeys'
import client from './client'
import type { ResourceApi } from './resources'

/** Where the passkey endpoints live, relative to the API base. */
const PASSKEYS_URL = '/v1/auth/passkeys'

/**
 * Fetch the options that let the browser create a passkey for the signed-in account.
 *
 * @returns The options; the server keeps their challenge for five minutes.
 */
async function registerOptions(): Promise<PublicKeyCredentialCreationOptionsJSON> {
    const { data } = await client.get<PublicKeyCredentialCreationOptionsJSON>(
        `${PASSKEYS_URL}/register/options`,
    )
    return data
}

/**
 * Save the passkey the browser created.
 *
 * @param credential - The browser's answer to the registration options.
 * @param nickname - The passkey's name, or null for none.
 * @returns The saved passkey.
 */
async function registerVerify(
    credential: RegistrationResponseJSON,
    nickname: string | null,
): Promise<Passkey> {
    const { data } = await client.post<Passkey>(`${PASSKEYS_URL}/register/verify`, {
        credential,
        nickname,
    })
    return data
}

/**
 * Add a passkey: fetch the options, let the browser create it, then save it.
 *
 * @param payload - The passkey's nickname.
 * @returns The saved passkey. A prompt that created nothing rejects with a message that
 *   says why, such as a dismissal.
 */
async function addPasskey(payload: PasskeyPayload): Promise<Passkey> {
    const optionsJSON = await registerOptions()
    let credential: RegistrationResponseJSON
    try {
        credential = await startRegistration({ optionsJSON })
    } catch (err: unknown) {
        throw registrationFailure(err)
    }
    return registerVerify(credential, payload.nickname)
}

/**
 * Fetch the signed-in account's passkeys.
 *
 * @returns The passkeys, oldest first.
 */
async function listPasskeys(): Promise<Passkey[]> {
    const { data } = await client.get<Passkey[]>(PASSKEYS_URL)
    return data
}

/**
 * Rename one of the signed-in account's passkeys.
 *
 * @param id - The passkey's id.
 * @param payload - The new nickname, or null to clear it.
 * @returns The renamed passkey.
 */
async function renamePasskey(id: number, payload: PasskeyPayload): Promise<Passkey> {
    const { data } = await client.put<Passkey>(`${PASSKEYS_URL}/${id}`, payload)
    return data
}

/**
 * Delete one of the signed-in account's passkeys.
 *
 * @param id - The passkey's id.
 * @returns A promise that settles when the passkey is gone; it rejects with the server's
 *   message when the passkey is the account's last way to sign in.
 */
async function deletePasskey(id: number): Promise<void> {
    await client.delete(`${PASSKEYS_URL}/${id}`)
}

/** The signed-in account's passkeys, in the shape `useResourceMutations` drives. */
export const passkeysApi: ResourceApi<Passkey, PasskeyPayload> = {
    list: listPasskeys,
    create: addPasskey,
    update: renamePasskey,
    remove: deletePasskey,
}

/**
 * Fetch the options that let the browser sign in with any of the site's passkeys.
 *
 * @returns The options, which name no credentials.
 */
export async function loginOptions(): Promise<PublicKeyCredentialRequestOptionsJSON> {
    const { data } = await client.get<PublicKeyCredentialRequestOptionsJSON>(
        `${PASSKEYS_URL}/login/options`,
    )
    return data
}

/**
 * Sign in with the passkey the browser chose.
 *
 * @param credential - The browser's answer to the sign-in options.
 * @returns The response wrapping the signed-in user, as `login` returns it.
 */
export const loginVerify = (credential: AuthenticationResponseJSON) =>
    client.post<AuthUser>(`${PASSKEYS_URL}/login/verify`, { credential })
