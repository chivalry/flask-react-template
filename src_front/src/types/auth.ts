/** @file Types describing the signed-in account. */

/** The access level of an account. */
export type Role = 'admin' | 'user'

/** A signed-in account as returned by the auth endpoints. */
export interface AuthUser {
    id: number
    uuid: string
    email: string
    role: Role
    created_at: string
    updated_at: string
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
