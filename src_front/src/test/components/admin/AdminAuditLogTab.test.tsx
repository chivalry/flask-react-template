/** @file The Audit tab opens on the last 30 days and refetches as its filters change. */

import { fireEvent, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { fetchAuditedTables, fetchAuditLogPage } from '../../../api/auditLogs'
import { usersApi } from '../../../api/users'
import AdminAuditLogTab from '../../../components/admin/AdminAuditLogTab'
import type { AuditLogFilters } from '../../../types/auditLog'
import { tableRowContaining } from '../../utils/dialogQueries'
import {
    adminUser,
    auditPage,
    plainUser,
    widgetCreated,
    widgetRenamed,
} from '../../utils/fixtures'
import { renderWithProviders } from '../../utils/renderWithProviders'

vi.mock('../../../api/auditLogs')
vi.mock('../../../api/users')

/** What the tab opens on at 6:30 PM on 2026-10-27, Los Angeles time. */
const OPENING_FILTERS: AuditLogFilters = {
    tableName: '',
    changedById: '',
    from: '2026-09-28',
    to: '2026-10-27',
}

const tableSelect = () => screen.getByRole('combobox', { name: /Table/ })
const userSelect = () => screen.getByRole('combobox', { name: /User/ })

/** The labels of the open dropdown's choices, in order. */
const optionLabels = () =>
    screen.getAllByRole('option').map((option) => option.textContent)

/** Wait for the first entries, which arrive after the table names and accounts. */
const findFirstEntry = () => screen.findByText('name: alpha → beta')

describe('AdminAuditLogTab', () => {
    beforeEach(() => {
        vi.clearAllMocks()
        // After 6:30 PM in Los Angeles it is already October 28 in UTC, where a
        // default range of UTC days would end a day late.
        vi.useFakeTimers({ toFake: ['Date'] })
        vi.setSystemTime(new Date(2026, 9, 27, 18, 30))
        vi.mocked(fetchAuditLogPage).mockResolvedValue(
            auditPage([widgetRenamed, widgetCreated]),
        )
        vi.mocked(fetchAuditedTables).mockResolvedValue(['users', 'widgets'])
        vi.mocked(usersApi.list).mockResolvedValue([adminUser, plainUser])
    })

    afterEach(() => {
        vi.useRealTimers()
    })

    it('opens on the last 30 local days, today included', async () => {
        renderWithProviders(<AdminAuditLogTab />)

        await findFirstEntry()
        expect(fetchAuditLogPage).toHaveBeenCalledExactlyOnceWith(OPENING_FILTERS, 1)
        expect(screen.getByLabelText('From')).toHaveValue('2026-09-28')
        expect(screen.getByLabelText('To')).toHaveValue('2026-10-27')
        // Each day bounds the other's picker, so the range cannot be chosen inverted.
        expect(screen.getByLabelText('From')).toHaveAttribute('max', '2026-10-27')
        expect(screen.getByLabelText('To')).toHaveAttribute('min', '2026-09-28')
    })

    it('offers every audited table and refetches with the chosen one', async () => {
        const user = userEvent.setup()
        renderWithProviders(<AdminAuditLogTab />)
        await findFirstEntry()

        expect(tableSelect()).toHaveTextContent('All tables')
        await user.click(tableSelect())
        await screen.findByRole('option', { name: 'users' })
        expect(optionLabels()).toEqual(['All tables', 'users', 'widgets'])
        await user.click(screen.getByRole('option', { name: 'users' }))

        await waitFor(() =>
            expect(fetchAuditLogPage).toHaveBeenLastCalledWith(
                { ...OPENING_FILTERS, tableName: 'users' },
                1,
            ),
        )
    })

    it('offers every account by email and refetches with the chosen id', async () => {
        const user = userEvent.setup()
        renderWithProviders(<AdminAuditLogTab />)
        await findFirstEntry()

        expect(userSelect()).toHaveTextContent('All users')
        await user.click(userSelect())
        await screen.findByRole('option', { name: plainUser.email })
        expect(optionLabels()).toEqual(['All users', adminUser.email, plainUser.email])
        await user.click(screen.getByRole('option', { name: plainUser.email }))

        await waitFor(() =>
            expect(fetchAuditLogPage).toHaveBeenLastCalledWith(
                { ...OPENING_FILTERS, changedById: '2' },
                1,
            ),
        )
    })

    it('refetches when the From or To day changes', async () => {
        renderWithProviders(<AdminAuditLogTab />)
        await findFirstEntry()

        fireEvent.change(screen.getByLabelText('From'), {
            target: { value: '2026-10-01' },
        })
        await waitFor(() =>
            expect(fetchAuditLogPage).toHaveBeenLastCalledWith(
                { ...OPENING_FILTERS, from: '2026-10-01' },
                1,
            ),
        )

        fireEvent.change(screen.getByLabelText('To'), { target: { value: '2026-10-20' } })
        await waitFor(() =>
            expect(fetchAuditLogPage).toHaveBeenLastCalledWith(
                { ...OPENING_FILTERS, from: '2026-10-01', to: '2026-10-20' },
                1,
            ),
        )
    })

    it("shows each entry's record beside its change", async () => {
        renderWithProviders(<AdminAuditLogTab />)

        await findFirstEntry()
        expect(screen.getByRole('columnheader', { name: 'Record' })).toBeInTheDocument()
        expect(
            tableRowContaining('name: alpha → beta').getByText('widgets · beta'),
        ).toBeInTheDocument()
    })

    it('says so when no change matches the filters', async () => {
        vi.mocked(fetchAuditLogPage).mockResolvedValue(auditPage([]))
        renderWithProviders(<AdminAuditLogTab />)

        expect(
            await screen.findByText('No changes match these filters.'),
        ).toBeInTheDocument()
    })
})
