/** @file Types for the admin's account management. */

import type { AuthUser, Role } from './auth'

/** An account as the users endpoint returns it. */
export type User = AuthUser

/** The body for creating or updating an account; `password` is required on create. */
export interface UserPayload {
    email: string
    password?: string
    role: Role
    is_active: boolean
}
