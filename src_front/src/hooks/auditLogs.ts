/** @file Server state for the audit log. */

import { useQuery } from '@tanstack/react-query'

import {
    fetchAuditedTables,
    fetchAuditLogPage,
    fetchRecordHistoryPage,
} from '../api/auditLogs'
import type { AuditLogFilters } from '../types/auditLog'
import { useInfiniteList } from './useInfiniteList'

/** Cache key prefix for every audit-log query. */
const AUDIT_LOGS_KEY = ['audit-logs'] as const

/**
 * Load one record's history page by page as the viewer scrolls.
 *
 * @param tableName - The audited table the record lives in.
 * @param recordId - The record's id.
 * @returns The infinite query holding the record's entries, newest first.
 */
export const useRecordHistory = (tableName: string, recordId: number) =>
    useInfiniteList({
        queryKey: [...AUDIT_LOGS_KEY, 'record', tableName, recordId],
        fetchPage: (page) => fetchRecordHistoryPage(tableName, recordId, page),
    })

/**
 * Load the admin's log page by page as the viewer scrolls.
 *
 * @param filters - The admin's filters; a change refetches from the first page.
 * @returns The infinite query holding the matching entries, newest first.
 */
export const useAuditLog = (filters: AuditLogFilters) =>
    useInfiniteList({
        queryKey: [...AUDIT_LOGS_KEY, 'all', filters],
        fetchPage: (page) => fetchAuditLogPage(filters, page),
    })

/** The infinite query both history hooks return, which `AuditLogTab` renders. */
export type AuditLogQuery = ReturnType<typeof useAuditLog>

/**
 * Load the names of the tables that keep a history; only admins may call the endpoint.
 *
 * @returns The query holding the table names.
 */
export const useAuditedTables = () =>
    useQuery({ queryKey: [...AUDIT_LOGS_KEY, 'tables'], queryFn: fetchAuditedTables })
