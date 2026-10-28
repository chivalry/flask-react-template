/** @file The audit-log endpoints send a record, the admin's filters, or the tables. */

import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
    fetchAuditedTables,
    fetchAuditLogPage,
    fetchRecordHistoryPage,
} from '../../api/auditLogs'
import client, { fetchPage } from '../../api/client'
import type { AuditLogFilters } from '../../types/auditLog'
import { auditPage, widgetCreated } from '../utils/fixtures'

vi.mock('../../api/client', () => ({ default: { get: vi.fn() }, fetchPage: vi.fn() }))

describe('audit log endpoints', () => {
    beforeEach(() => {
        vi.resetAllMocks()
    })

    it("pages through one record's history on /v1/audit-logs", async () => {
        const page = auditPage([widgetCreated])
        vi.mocked(fetchPage).mockResolvedValue(page)

        await expect(fetchRecordHistoryPage('users', 7, 2)).resolves.toBe(page)

        expect(fetchPage).toHaveBeenCalledExactlyOnceWith('/v1/audit-logs', 2, {
            table_name: 'users',
            record_id: 7,
        })
    })

    it('sends the filters, with the days as the moments that bound them', async () => {
        const page = auditPage([widgetCreated])
        vi.mocked(fetchPage).mockResolvedValue(page)
        const filters: AuditLogFilters = {
            tableName: 'users',
            changedById: '3',
            from: '2026-10-01',
            to: '2026-11-01',
        }

        await expect(fetchAuditLogPage(filters, 1)).resolves.toBe(page)

        // Local midnight of October 1 is 07:00 UTC; the range ends before the local
        // midnight after November 1, which falls after daylight saving ended.
        expect(fetchPage).toHaveBeenCalledExactlyOnceWith('/v1/audit-logs/all', 1, {
            table_name: 'users',
            changed_by_id: '3',
            changed_from: '2026-10-01T07:00:00.000Z',
            changed_before: '2026-11-02T08:00:00.000Z',
        })
    })

    it('sends no parameter for a blank filter', async () => {
        vi.mocked(fetchPage).mockResolvedValue(auditPage([]))
        const blank: AuditLogFilters = {
            tableName: '',
            changedById: '',
            from: '',
            to: '',
        }

        await fetchAuditLogPage(blank, 3)

        expect(fetchPage).toHaveBeenCalledExactlyOnceWith('/v1/audit-logs/all', 3, {
            table_name: undefined,
            changed_by_id: undefined,
            changed_from: undefined,
            changed_before: undefined,
        })
    })

    it('lists the audited tables from /v1/audit-logs/tables', async () => {
        vi.mocked(client.get).mockResolvedValue({ data: ['users', 'widgets'] })

        await expect(fetchAuditedTables()).resolves.toEqual(['users', 'widgets'])

        expect(client.get).toHaveBeenCalledExactlyOnceWith('/v1/audit-logs/tables')
    })
})
