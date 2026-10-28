/** @file A record's change history, for the history tab of its detail view. */

import { useRecordHistory } from '../../hooks/auditLogs'
import AuditLogTab from './AuditLogTab'

/** Props accepted by {@link RecordAuditLogTab}. */
interface RecordAuditLogTabProps {
    /** The audited table the record lives in, such as `users`. */
    tableName: string
    /** The record's id. */
    recordId: number
}

/**
 * Show one record's history, newest change first.
 *
 * The table must be audited, or the server answers 404, and an admin-only table's
 * history, such as the accounts', answers 403 to anyone but an admin.
 *
 * @param props - The component props.
 * @returns The history table.
 */
export default function RecordAuditLogTab(props: RecordAuditLogTabProps) {
    const { tableName, recordId } = props
    return <AuditLogTab query={useRecordHistory(tableName, recordId)} />
}
