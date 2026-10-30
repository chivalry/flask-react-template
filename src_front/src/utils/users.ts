/** @file How an account reads in lists and headings. */

import type { User } from '../types/users'

/**
 * Describe an account's role and whether it is deactivated.
 *
 * @param user - The account.
 * @returns For example `admin` or `user · inactive`.
 */
export function describeUser(user: User): string {
    return user.is_active ? user.role : `${user.role} · inactive`
}
