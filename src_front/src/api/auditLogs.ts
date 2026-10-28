/** @file Endpoints for the audit log: a record's history, the admin's log, the tables. */

import type { AuditLogEntry, AuditLogFilters } from '../types/auditLog'
import { addLocalDays, localDayStartIso } from '../utils/dates'
import client, { fetchPage } from './client'

const AUDIT_LOGS_URL = '/v1/audit-logs'

/**
 * Fetch one page of one record's history, newest change first.
 *
 * @param tableName - The audited table the record lives in.
 * @param recordId - The record's id.
 * @param page - The 1-based page number to request.
 * @returns The page envelope: the entries plus the pagination metadata.
 */
export const fetchRecordHistoryPage = (
    tableName: string,
    recordId: number,
    page: number,
) =>
    fetchPage<AuditLogEntry>(AUDIT_LOGS_URL, page, {
        table_name: tableName,
        record_id: recordId,
    })

/**
 * Turn the admin's filters into the log's query parameters.
 *
 * A blank filter becomes `undefined`, which axios leaves out of the request. The range
 * of local days goes out as the moments that bound it: from the first day's local
 * midnight up to, not including, the midnight after the last day.
 *
 * @param filters - The admin's filters.
 * @returns The query parameters.
 */
function auditLogParams(filters: AuditLogFilters): Record<string, unknown> {
    return {
        table_name: filters.tableName || undefined,
        changed_by_id: filters.changedById || undefined,
        changed_from: filters.from ? localDayStartIso(filters.from) : undefined,
        changed_before: filters.to
            ? localDayStartIso(addLocalDays(filters.to, 1))
            : undefined,
    }
}

/**
 * Fetch one page of the admin's log, newest change first.
 *
 * @param filters - The admin's filters.
 * @param page - The 1-based page number to request.
 * @returns The page envelope: the entries plus the pagination metadata.
 */
export const fetchAuditLogPage = (filters: AuditLogFilters, page: number) =>
    fetchPage<AuditLogEntry>(`${AUDIT_LOGS_URL}/all`, page, auditLogParams(filters))

/**
 * Fetch the names of the tables that keep a history.
 *
 * @returns The table names, in order.
 */
export async function fetchAuditedTables(): Promise<string[]> {
    const { data } = await client.get<string[]>(`${AUDIT_LOGS_URL}/tables`)
    return data
}
