/** @file Endpoints for the admin's account management. */

import type { User, UserPayload } from '../types/users'
import { resource } from './resources'

/**
 * The account endpoints, which only admins may call.
 *
 * The server has no delete route: an account is deactivated, never deleted, so
 * `remove` would answer 405 and nothing calls it.
 */
export const usersApi = resource<User, UserPayload>('/v1/users')
