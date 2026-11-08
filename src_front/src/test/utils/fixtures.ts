/** @file Test accounts, a passkey, and audit entries: an admin, a user, a widget. */

import type { AuditLogEntry } from '../../types/auditLog'
import type {
    AuthUser,
    LinkedAccount,
    OAuthProviderInfo,
    Passkey,
} from '../../types/auth'
import type { PaginatedResponse } from '../../types/pagination'

const stamps = { created_at: '2026-10-10T00:00:00Z', updated_at: '2026-10-10T00:00:00Z' }

export const adminUser: AuthUser = {
    id: 1,
    uuid: 'user-uuid-1',
    email: 'admin@example.com',
    role: 'admin',
    has_password: true,
    is_active: true,
    ...stamps,
}

export const plainUser: AuthUser = {
    id: 2,
    uuid: 'user-uuid-2',
    email: 'user@example.com',
    role: 'user',
    has_password: true,
    is_active: true,
    ...stamps,
}

/** Google, as the providers route lists it once its keys are set. */
export const googleProvider: OAuthProviderInfo = { name: 'google', label: 'Google' }

/** Apple, as the providers route lists it once its four keys are set over https. */
export const appleProvider: OAuthProviderInfo = { name: 'apple', label: 'Apple' }

/** Facebook, as the providers route lists it once both of its keys are set. */
export const facebookProvider: OAuthProviderInfo = { name: 'facebook', label: 'Facebook' }

/** The signed-in account's link to a Google identity with an address of its own. */
export const linkedGoogleAccount: LinkedAccount = {
    id: 1,
    uuid: 'oauth-uuid-1',
    provider: 'google',
    email: 'user@gmail.com',
    display_name: 'Plain User',
    ...stamps,
}

/** The signed-in account's synced laptop passkey, last used on October 14. */
export const laptopPasskey: Passkey = {
    id: 3,
    uuid: 'passkey-uuid-3',
    nickname: 'Laptop',
    aaguid: '00000000-0000-0000-0000-000000000000',
    transports: 'internal,hybrid',
    backup_eligible: true,
    backup_state: true,
    last_used_at: '2026-10-14T16:05:00Z',
    ...stamps,
}

/** An admin's rename of widget 4, which also switched it off. */
export const widgetRenamed: AuditLogEntry = {
    id: 2,
    uuid: 'audit-uuid-2',
    table_name: 'widgets',
    record_id: 4,
    record_label: 'beta',
    action: 'updated',
    changes: { name: { old: 'alpha', new: 'beta' }, active: { old: true, new: false } },
    changed_by_id: adminUser.id,
    changed_by_name: adminUser.email,
    changed_at: '2026-10-14T16:05:00Z',
    created_at: '2026-10-14T16:05:00Z',
    updated_at: '2026-10-14T16:05:00Z',
}

/** The creation of widget 4 outside a signed-in request, so with no actor. */
export const widgetCreated: AuditLogEntry = {
    id: 1,
    uuid: 'audit-uuid-1',
    table_name: 'widgets',
    record_id: 4,
    record_label: 'alpha',
    action: 'created',
    changes: { name: 'alpha', note: null, code: '' },
    changed_by_id: null,
    changed_by_name: null,
    changed_at: '2026-10-14T15:00:00Z',
    created_at: '2026-10-14T15:00:00Z',
    updated_at: '2026-10-14T15:00:00Z',
}

/** Wrap entries in the pagination envelope the history routes answer with. */
export const auditPage = (
    items: AuditLogEntry[],
    page = 1,
    total = items.length,
    perPage = 100,
): PaginatedResponse<AuditLogEntry> => ({
    items,
    total,
    page,
    pages: Math.ceil(total / perPage),
    per_page: perPage,
})
