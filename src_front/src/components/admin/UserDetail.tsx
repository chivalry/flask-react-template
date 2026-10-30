/** @file One account's detail: its heading, how it signs in, history, and activity. */

import { Chip, Stack, Typography } from '@mui/material'

import { useAuditLog } from '../../hooks/auditLogs'
import type { User } from '../../types/users'
import { formatLocalDateTime } from '../../utils/dates'
import { describeUser } from '../../utils/users'
import AuditLogTab from '../common/AuditLogTab'
import DetailColumns from '../common/DetailColumns'
import DetailHeader from '../common/DetailHeader'
import LabeledRow from '../common/LabeledRow'
import RecordAuditLogTab from '../common/RecordAuditLogTab'
import ChildPortal from '../layout/ChildPortal'

/** Props accepted by {@link UserDetail}. */
interface UserDetailProps {
    user: User
    /** The selected tab of the account's history, as the URL holds it. */
    tab: string
    onTabChange: (tab: string) => void
    onEdit: () => void
}

/** Props accepted by {@link AccountActivity}. */
interface AccountActivityProps {
    userId: number
}

/**
 * Show the changes an account made, to any record, newest first.
 *
 * @param props - The component props.
 * @returns The activity table.
 */
function AccountActivity(props: AccountActivityProps) {
    const query = useAuditLog({
        tableName: '',
        changedById: String(props.userId),
        from: '',
        to: '',
    })
    return <AuditLogTab query={query} showRecord emptyText="No activity yet." />
}

/**
 * Build the tabs of an account's history: the changes made to it, then by it.
 *
 * @param userId - The account's id.
 * @returns The History and Activity tabs.
 */
function accountTabs(userId: number) {
    return [
        {
            value: 'history',
            label: 'History',
            content: <RecordAuditLogTab tableName="users" recordId={userId} />,
        },
        {
            value: 'activity',
            label: 'Activity',
            content: <AccountActivity userId={userId} />,
        },
    ]
}

/**
 * Render the account's heading and Edit, how it signs in and when it was created, and
 * its history and activity.
 *
 * Accounts are deactivated, never deleted, so the header offers no Delete.
 *
 * @param props - The component props.
 * @returns The detail element.
 */
export default function UserDetail(props: UserDetailProps) {
    const { user, tab, onTabChange, onEdit } = props
    return (
        <Stack spacing={3} sx={{ p: 2 }}>
            <DetailHeader
                title={user.email}
                subtitle={describeUser(user)}
                onEdit={onEdit}
            />
            <DetailColumns
                left={
                    <LabeledRow label="Sign-in">
                        <Chip
                            size="small"
                            label={user.has_password ? 'Password' : 'No password'}
                        />
                    </LabeledRow>
                }
                right={
                    <LabeledRow label="Created">
                        <Typography variant="body2">
                            {formatLocalDateTime(user.created_at)}
                        </Typography>
                    </LabeledRow>
                }
            />
            <ChildPortal
                label="Account history"
                tabs={accountTabs(user.id)}
                value={tab}
                onChange={onTabChange}
            />
        </Stack>
    )
}
