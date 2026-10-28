/** @file AuditLogTab shows entries as rows, counts them, and pages without repeats. */

import { act, screen, waitFor } from '@testing-library/react'
import type { ComponentProps } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { fetchRecordHistoryPage } from '../../../api/auditLogs'
import AuditLogTab from '../../../components/common/AuditLogTab'
import { useRecordHistory } from '../../../hooks/auditLogs'
import type { AuditLogEntry } from '../../../types/auditLog'
import { formatLocalDateTime } from '../../../utils/dates'
import { tableRowContaining } from '../../utils/dialogQueries'
import { adminUser, auditPage, widgetCreated, widgetRenamed } from '../../utils/fixtures'
import { renderWithProviders } from '../../utils/renderWithProviders'

vi.mock('../../../api/auditLogs')

type HistoryProps = Pick<ComponentProps<typeof AuditLogTab>, 'showRecord' | 'emptyText'>

/** Show widget 4's history in the tab, as a record's detail view does. */
function History(props: HistoryProps) {
    return <AuditLogTab query={useRecordHistory('widgets', 4)} {...props} />
}

const renderHistory = (props: HistoryProps = {}) =>
    renderWithProviders(<History {...props} />)

/** The entry rows of the table, which follow its header row. */
const entryRows = () => screen.getAllByRole('row').slice(1)

describe('AuditLogTab', () => {
    beforeEach(() => {
        vi.clearAllMocks()
        vi.mocked(fetchRecordHistoryPage).mockResolvedValue(
            auditPage([widgetRenamed, widgetCreated]),
        )
    })

    it('shows an update with its date, actor, action, and changed fields', async () => {
        renderHistory()

        await screen.findByText('name: alpha → beta')
        const row = tableRowContaining('name: alpha → beta')
        expect(
            row.getByText(formatLocalDateTime(widgetRenamed.changed_at)),
        ).toBeInTheDocument()
        expect(row.getByText(adminUser.email)).toBeInTheDocument()
        expect(row.getByText('updated')).toBeInTheDocument()
        expect(row.getByText('active: true → false')).toBeInTheDocument()
    })

    it('shows a create as its audited fields, with a dash for no actor', async () => {
        renderHistory()

        await screen.findByText('name: alpha')
        const row = tableRowContaining('name: alpha')
        expect(row.getByText('created')).toBeInTheDocument()
        expect(row.getByText('note: —')).toBeInTheDocument()
        expect(row.getByText('code: —')).toBeInTheDocument()
        expect(row.getByText('—')).toBeInTheDocument()
    })

    it('shows an object value as JSON', async () => {
        const tagged: AuditLogEntry = {
            ...widgetRenamed,
            changes: { tags: { old: ['a'], new: ['a', 'b'] } },
        }
        vi.mocked(fetchRecordHistoryPage).mockResolvedValue(auditPage([tagged]))
        renderHistory()

        expect(await screen.findByText('tags: ["a"] → ["a","b"]')).toBeInTheDocument()
    })

    it.each([
        { label: 'beta', record: 'widgets · beta' },
        { label: null, record: 'widgets · #4' },
    ])('names the record $record when asked to show it', async ({ label, record }) => {
        const labeled: AuditLogEntry = { ...widgetRenamed, record_label: label }
        vi.mocked(fetchRecordHistoryPage).mockResolvedValue(auditPage([labeled]))
        renderHistory({ showRecord: true })

        expect(await screen.findByText(record)).toBeInTheDocument()
        expect(screen.getByRole('columnheader', { name: 'Record' })).toBeInTheDocument()
    })

    it.each([
        { entries: [widgetRenamed, widgetCreated], caption: '2 entries' },
        { entries: [widgetCreated], caption: '1 entry' },
    ])('captions the history $caption', async ({ entries, caption }) => {
        vi.mocked(fetchRecordHistoryPage).mockResolvedValue(auditPage(entries))
        renderHistory()

        expect(await screen.findByText(caption)).toBeInTheDocument()
    })

    it.each([
        { props: {}, text: 'No history yet.' },
        { props: { emptyText: 'Nothing was changed.' }, text: 'Nothing was changed.' },
    ])('says $text when there are no entries', async ({ props, text }) => {
        vi.mocked(fetchRecordHistoryPage).mockResolvedValue(auditPage([]))
        renderHistory(props)

        expect(await screen.findByText(text)).toBeInTheDocument()
        expect(screen.queryByRole('table')).not.toBeInTheDocument()
        expect(screen.queryByText(/entr(y|ies)$/)).not.toBeInTheDocument()
    })

    describe('scrolling to the end of a page', () => {
        afterEach(() => vi.unstubAllGlobals())

        it('loads the next page and shows an entry it repeats once', async () => {
            let reportIntersection: IntersectionObserverCallback = () => undefined
            vi.stubGlobal(
                'IntersectionObserver',
                class {
                    constructor(listener: IntersectionObserverCallback) {
                        reportIntersection = listener
                    }
                    observe = vi.fn()
                    disconnect = vi.fn()
                },
            )
            const widgetDeleted: AuditLogEntry = {
                ...widgetCreated,
                id: 3,
                uuid: 'audit-uuid-3',
                action: 'deleted',
                changed_at: '2026-10-14T17:00:00Z',
            }
            // An entry recorded between the loads pushes widgetRenamed onto page 2.
            vi.mocked(fetchRecordHistoryPage)
                .mockResolvedValueOnce(auditPage([widgetDeleted, widgetRenamed], 1, 3, 2))
                .mockResolvedValueOnce(auditPage([widgetRenamed, widgetCreated], 2, 3, 2))
            renderHistory()

            await screen.findByText('name: alpha → beta')
            expect(entryRows()).toHaveLength(2)

            await act(async () => {
                reportIntersection(
                    [{ isIntersecting: true } as IntersectionObserverEntry],
                    {} as IntersectionObserver,
                )
            })

            await waitFor(() => expect(entryRows()).toHaveLength(3))
            expect(fetchRecordHistoryPage).toHaveBeenLastCalledWith('widgets', 4, 2)
        })
    })
})
