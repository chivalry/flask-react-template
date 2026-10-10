/** @file Authentication endpoints: register, login, logout, and identity. */

import type { AuthUser } from '../types/auth'
import client from './client'

/** The body the logout endpoint returns. */
interface LogoutResponse {
    message: string
}

/**
 * Create an account.
 *
 * @param email - The address to register.
 * @param password - The chosen password, at least 8 characters.
 * @returns The response wrapping the newly created user.
 */
export const register = (email: string, password: string) =>
    client.post<AuthUser>('/v1/auth/register', { email, password })

/**
 * Sign in and start a session.
 *
 * @param email - The account's address.
 * @param password - The account's password.
 * @returns The response wrapping the signed-in user.
 */
export const login = (email: string, password: string) =>
    client.post<AuthUser>('/v1/auth/login', { email, password })

/**
 * End the current session.
 *
 * @returns The response confirming sign-out.
 */
export const logout = () => client.post<LogoutResponse>('/v1/auth/logout')

/**
 * Fetch the signed-in user, used to restore auth state on page load.
 *
 * @returns The response wrapping the current user; rejects with a 401 when no
 *   session is active.
 */
export const me = () => client.get<AuthUser>('/v1/auth/me')
