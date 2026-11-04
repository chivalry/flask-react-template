/** @file Types describing the signed-in account. */

/** The access level of an account. */
export type Role = 'admin' | 'user'

/** A signed-in account as returned by the auth endpoints. */
export interface AuthUser {
    id: number
    uuid: string
    email: string
    role: Role
    /** False for an account a sign-in provider created without a password. */
    has_password: boolean
    /** False once an admin deactivates the account. */
    is_active: boolean
    created_at: string
    updated_at: string
}

/** A sign-in provider the server has enabled. */
export interface OAuthProviderInfo {
    name: string
    label: string
}

/** A provider identity linked to the signed-in account. */
export interface LinkedAccount {
    id: number
    uuid: string
    provider: string
    /** The address the provider gave, which may differ from the account's. */
    email: string | null
    display_name: string | null
    created_at: string
    updated_at: string
}

/** A passkey that can sign in to the signed-in account. */
export interface Passkey {
    id: number
    uuid: string
    /** The name the account gave it, or null for none. */
    nickname: string | null
    /** The authenticator model's id; all zeros when it keeps that private. */
    aaguid: string | null
    /** The browser's comma-joined transport hints, such as `internal,hybrid`. */
    transports: string | null
    /** Whether the passkey can sync to the person's other devices. */
    backup_eligible: boolean
    /** Whether it has synced. */
    backup_state: boolean
    /** When it last answered a sign-in, or null if it never has. */
    last_used_at: string | null
    created_at: string
    updated_at: string
}

/** The body that names a passkey, when adding or renaming it. */
export interface PasskeyPayload {
    nickname: string | null
}

/**
 * Tell whether a role grants administrative access.
 *
 * @param role - The role to check.
 * @returns True when the role is `admin`.
 */
export function isAdmin(role: Role): boolean {
    return role === 'admin'
}
