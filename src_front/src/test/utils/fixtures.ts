/** @file Accounts and audit entries shared by the tests: an admin, a user, a widget. */

import type { AuditLogEntry } from '../../types/auditLog'
import type { AuthUser } from '../../types/auth'
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
