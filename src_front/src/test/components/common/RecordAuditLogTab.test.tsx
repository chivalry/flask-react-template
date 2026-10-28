/** @file RecordAuditLogTab shows the history of the record it is given. */

import { screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { fetchRecordHistoryPage } from '../../../api/auditLogs'
import RecordAuditLogTab from '../../../components/common/RecordAuditLogTab'
import { auditPage, widgetCreated, widgetRenamed } from '../../utils/fixtures'
import { renderWithProviders } from '../../utils/renderWithProviders'

vi.mock('../../../api/auditLogs')

describe('RecordAuditLogTab', () => {
    beforeEach(() => {
        vi.clearAllMocks()
        vi.mocked(fetchRecordHistoryPage).mockResolvedValue(
            auditPage([widgetRenamed, widgetCreated]),
        )
    })

    it("requests the record's first page and renders its entries", async () => {
        renderWithProviders(<RecordAuditLogTab tableName="users" recordId={7} />)

        expect(await screen.findByText('name: alpha → beta')).toBeInTheDocument()
        expect(screen.getByText('name: alpha')).toBeInTheDocument()
        expect(fetchRecordHistoryPage).toHaveBeenCalledExactlyOnceWith('users', 7, 1)
        // One record's history needs no column naming the record.
        expect(
            screen.queryByRole('columnheader', { name: 'Record' }),
        ).not.toBeInTheDocument()
    })
})
