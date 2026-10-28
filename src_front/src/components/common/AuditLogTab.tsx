/** @file Table of audit entries that loads further pages as the viewer scrolls. */

import {
    Chip,
    Table,
    TableBody,
    TableCell,
    TableContainer,
    TableHead,
    TableRow,
    Typography,
} from '@mui/material'

import type { AuditLogQuery } from '../../hooks/auditLogs'
import { flattenPages, lastLoadedPageTotal } from '../../hooks/useInfiniteList'
import type { AuditAction, AuditLogEntry } from '../../types/auditLog'
import { formatLocalDateTime } from '../../utils/dates'
import InfiniteScrollSentinel from './InfiniteScrollSentinel'
import QueryState from './QueryState'

/** Props accepted by {@link AuditLogTab}. */
interface AuditLogTabProps {
    /** The infinite query holding the entries, such as `useRecordHistory`'s. */
    query: AuditLogQuery
    /** Adds a Record column, for a log of many records. */
    showRecord?: boolean
    /** What to say when there are no entries; defaults to `No history yet.`. */
    emptyText?: string
}

/** Props accepted by {@link EntryRow}. */
interface EntryRowProps {
    entry: AuditLogEntry
    showRecord: boolean
}

/** Props accepted by {@link EntryTable}. */
interface EntryTableProps {
    entries: AuditLogEntry[]
    showRecord: boolean
    emptyText: string
}

/** The chip color of each action. */
const ACTION_COLORS: Record<AuditAction, 'success' | 'info' | 'error'> = {
    created: 'success',
    updated: 'info',
    deleted: 'error',
}

/**
 * Show a recorded value as one line of text.
 *
 * @param value - The value, as the server's JSON carried it.
 * @returns A dash for `null` and an empty string, a string as it is, an object as
 *   JSON, and anything else as plain text.
 */
function formatValue(value: unknown): string {
    if (value === null || value === '') return '—'
    if (typeof value === 'string') return value
    if (typeof value === 'object') return JSON.stringify(value)
    return String(value)
}

/**
 * List what an entry recorded, one line per field.
 *
 * @param entry - The audit entry.
 * @returns `field: old → new` for each field an update changed, and `field: value`
 *   for each audited field a create or delete holds.
 */
function describeChanges(entry: AuditLogEntry): string[] {
    if (entry.action === 'updated') {
        return Object.entries(entry.changes).map(
            ([field, change]) =>
                `${field}: ${formatValue(change.old)} → ${formatValue(change.new)}`,
        )
    }
    return Object.entries(entry.changes).map(
        ([field, value]) => `${field}: ${formatValue(value)}`,
    )
}

/**
 * Name the record an entry describes, for a log of many records.
 *
 * @param entry - The audit entry.
 * @returns The table and the record's label, or its id when it had no label, for
 *   example `widgets · beta` or `widgets · #4`.
 */
function describeRecord(entry: AuditLogEntry): string {
    return `${entry.table_name} · ${entry.record_label ?? `#${entry.record_id}`}`
}

/**
 * Keep the first entry with each id.
 *
 * Entries recorded while the viewer scrolls push older ones onto the next page, so a
 * later page can repeat an entry an earlier page showed.
 *
 * @param entries - The entries of every loaded page, in page order.
 * @returns The entries without repeats.
 */
function uniqueEntries(entries: AuditLogEntry[]): AuditLogEntry[] {
    const seen = new Set<number>()
    return entries.filter((entry) => {
        if (seen.has(entry.id)) return false
        seen.add(entry.id)
        return true
    })
}

/**
 * Render one entry as a table row.
 *
 * @param props - The component props.
 * @returns The row element.
 */
function EntryRow(props: EntryRowProps) {
    const { entry, showRecord } = props
    return (
        <TableRow>
            <TableCell>{formatLocalDateTime(entry.changed_at)}</TableCell>
            <TableCell>{entry.changed_by_name ?? '—'}</TableCell>
            <TableCell>
                <Chip
                    size="small"
                    label={entry.action}
                    color={ACTION_COLORS[entry.action]}
                />
            </TableCell>
            {showRecord && <TableCell>{describeRecord(entry)}</TableCell>}
            <TableCell>
                {describeChanges(entry).map((line) => (
                    <Typography key={line} variant="body2">
                        {line}
                    </Typography>
                ))}
            </TableCell>
        </TableRow>
    )
}

/**
 * Render the entries as a table, or say there are none.
 *
 * @param props - The component props.
 * @returns The table, or the empty text.
 */
function EntryTable(props: EntryTableProps) {
    const { entries, showRecord, emptyText } = props
    if (entries.length === 0) {
        return (
            <Typography color="text.secondary" sx={{ p: 2 }}>
                {emptyText}
            </Typography>
        )
    }
    return (
        <TableContainer>
            <Table size="small" aria-label="Audit log">
                <TableHead>
                    <TableRow>
                        <TableCell>Date</TableCell>
                        <TableCell>User</TableCell>
                        <TableCell>Action</TableCell>
                        {showRecord && <TableCell>Record</TableCell>}
                        <TableCell>Changes</TableCell>
                    </TableRow>
                </TableHead>
                <TableBody>
                    {entries.map((entry) => (
                        <EntryRow key={entry.id} entry={entry} showRecord={showRecord} />
                    ))}
                </TableBody>
            </Table>
        </TableContainer>
    )
}

/**
 * Render an audit history: how many entries there are, then the entries, newest first.
 *
 * The count sits outside {@link QueryState}, where the total is still unknown while
 * the first page loads, so it shows nothing until then. The query pages with
 * {@link InfiniteScrollSentinel}, and an entry a later page repeats is shown once.
 *
 * @param props - The component props.
 * @returns The count, the table, and the marker that loads the next page.
 */
export default function AuditLogTab(props: AuditLogTabProps) {
    const { query, showRecord = false, emptyText = 'No history yet.' } = props
    const total = lastLoadedPageTotal(query.data)
    return (
        <>
            {total ? (
                <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
                    {total === 1 ? '1 entry' : `${total} entries`}
                </Typography>
            ) : null}
            <QueryState query={query}>
                {(data) => (
                    <>
                        <EntryTable
                            entries={uniqueEntries(flattenPages(data))}
                            showRecord={showRecord}
                            emptyText={emptyText}
                        />
                        <InfiniteScrollSentinel
                            hasNextPage={query.hasNextPage}
                            isFetchingNextPage={query.isFetchingNextPage}
                            fetchNextPage={() => void query.fetchNextPage()}
                        />
                    </>
                )}
            </QueryState>
        </>
    )
}
