/** @file Types for the audit log: its entries and the filters of the admin's log. */

/** What happened to the record an entry describes. */
export type AuditAction = 'created' | 'updated' | 'deleted'

/** One field an update changed, with its value before and after. */
export interface AuditFieldChange {
    old: unknown
    new: unknown
}

/** The fields every entry carries, whatever its action. */
interface AuditLogEntryBase {
    id: number
    uuid: string
    table_name: string
    record_id: number
    /** The record's name when the change was made; null for a table with no label. */
    record_label: string | null
    /** Null for a change made outside a signed-in request, or by a deleted account. */
    changed_by_id: number | null
    changed_by_name: string | null
    changed_at: string
    created_at: string
    updated_at: string
}

/** An update lists each changed field; a create or delete holds the audited fields. */
export type AuditLogEntry =
    | (AuditLogEntryBase & {
          action: 'updated'
          changes: Record<string, AuditFieldChange>
      })
    | (AuditLogEntryBase & {
          action: 'created' | 'deleted'
          changes: Record<string, unknown>
      })

/**
 * What the admin's log is filtered by.
 *
 * An empty string means any. `from` and `to` are local `YYYY-MM-DD` days, both
 * included.
 */
export interface AuditLogFilters {
    tableName: string
    changedById: string
    from: string
    to: string
}
