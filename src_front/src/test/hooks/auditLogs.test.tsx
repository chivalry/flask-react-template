/** @file The audit-log hooks load their pages and tables through the audit-log API. */

import { renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
    fetchAuditedTables,
    fetchAuditLogPage,
    fetchRecordHistoryPage,
} from '../../api/auditLogs'
import { useAuditedTables, useAuditLog, useRecordHistory } from '../../hooks/auditLogs'
import type { AuditLogFilters } from '../../types/auditLog'
import { auditPage, widgetCreated, widgetRenamed } from '../utils/fixtures'
import Providers from '../utils/Providers'

vi.mock('../../api/auditLogs')

const filters: AuditLogFilters = {
    tableName: 'users',
    changedById: '2',
    from: '2026-10-01',
    to: '2026-10-20',
}

describe('audit log hooks', () => {
    beforeEach(() => {
        vi.clearAllMocks()
    })

    it('useRecordHistory loads page 1 through fetchRecordHistoryPage', async () => {
        const page = auditPage([widgetRenamed, widgetCreated])
        vi.mocked(fetchRecordHistoryPage).mockResolvedValue(page)

        const { result } = renderHook(() => useRecordHistory('users', 7), {
            wrapper: Providers,
        })

        await waitFor(() => expect(result.current.data?.pages).toEqual([page]))
        expect(fetchRecordHistoryPage).toHaveBeenCalledExactlyOnceWith('users', 7, 1)
    })

    it('useAuditLog loads the first page through fetchAuditLogPage', async () => {
        const page = auditPage([widgetRenamed])
        vi.mocked(fetchAuditLogPage).mockResolvedValue(page)

        const { result } = renderHook(() => useAuditLog(filters), {
            wrapper: Providers,
        })

        await waitFor(() => expect(result.current.data?.pages).toEqual([page]))
        expect(fetchAuditLogPage).toHaveBeenCalledExactlyOnceWith(filters, 1)
    })

    it("useAuditedTables returns the API's table names", async () => {
        vi.mocked(fetchAuditedTables).mockResolvedValue(['users', 'widgets'])

        const { result } = renderHook(() => useAuditedTables(), { wrapper: Providers })

        await waitFor(() => expect(result.current.data).toEqual(['users', 'widgets']))
        expect(fetchAuditedTables).toHaveBeenCalledTimes(1)
    })
})
