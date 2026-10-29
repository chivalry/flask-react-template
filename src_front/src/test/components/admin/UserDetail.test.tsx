/** @file An account's detail shows its heading, sign-in, creation time, and history. */

import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { fetchAuditLogPage, fetchRecordHistoryPage } from '../../../api/auditLogs'
import UserDetail from '../../../components/admin/UserDetail'
import type { User } from '../../../types/users'
import { formatLocalDateTime } from '../../../utils/dates'
import { auditPage, plainUser, widgetRenamed } from '../../utils/fixtures'
import { renderWithProviders } from '../../utils/renderWithProviders'

vi.mock('../../../api/auditLogs')

/** Render an account's detail on a tab, with handlers that record their calls. */
const renderDetail = (account: User = plainUser, tab = '') => {
    const handlers = { onTabChange: vi.fn(), onEdit: vi.fn() }
    renderWithProviders(<UserDetail user={account} tab={tab} {...handlers} />)
    return handlers
}

describe('UserDetail', () => {
    beforeEach(() => {
        vi.clearAllMocks()
        vi.mocked(fetchRecordHistoryPage).mockResolvedValue(auditPage([]))
        vi.mocked(fetchAuditLogPage).mockResolvedValue(auditPage([]))
    })

    it('heads the detail with email and role, with Edit but no Delete', async () => {
        const user = userEvent.setup()
        const { onEdit } = renderDetail()

        expect(
            await screen.findByRole('heading', { level: 1, name: plainUser.email }),
        ).toBeInTheDocument()
        expect(screen.getByText('user')).toBeInTheDocument()
        expect(screen.queryByRole('button', { name: 'Delete' })).not.toBeInTheDocument()
        await user.click(screen.getByRole('button', { name: 'Edit' }))

        expect(onEdit).toHaveBeenCalledOnce()
    })

    it('shows how the account signs in and when it was created', async () => {
        // The account changed after it was created, so the two stamps differ.
        renderDetail({ ...plainUser, updated_at: '2026-10-12T09:30:00Z' })

        const signIn = await screen.findByText('Sign-in')
        expect(signIn.parentElement?.textContent).toBe('Sign-inPassword')
        expect(screen.getByText('Created').parentElement?.textContent).toBe(
            `Created${formatLocalDateTime(plainUser.created_at)}`,
        )
    })

    it('says so when the account has no password', async () => {
        renderDetail({ ...plainUser, has_password: false })

        const signIn = await screen.findByText('Sign-in')
        expect(signIn.parentElement?.textContent).toBe('Sign-inNo password')
    })

    it("opens on the History tab, which loads the account's history", async () => {
        renderDetail()

        expect(await screen.findByText('No history yet.')).toBeInTheDocument()
        expect(screen.getByRole('tab', { name: 'History' })).toHaveAttribute(
            'aria-selected',
            'true',
        )
        expect(fetchRecordHistoryPage).toHaveBeenCalledExactlyOnceWith('users', 2, 1)
        expect(fetchAuditLogPage).not.toHaveBeenCalled()
    })

    it('shows the changes the account made on the Activity tab', async () => {
        vi.mocked(fetchAuditLogPage).mockResolvedValue(auditPage([widgetRenamed]))
        renderDetail(plainUser, 'activity')

        expect(
            await screen.findByRole('columnheader', { name: 'Record' }),
        ).toBeInTheDocument()
        expect(screen.getByRole('tab', { name: 'Activity' })).toHaveAttribute(
            'aria-selected',
            'true',
        )
        expect(fetchAuditLogPage).toHaveBeenCalledExactlyOnceWith(
            { tableName: '', changedById: '2', from: '', to: '' },
            1,
        )
        expect(fetchRecordHistoryPage).not.toHaveBeenCalled()
    })

    it('reports the Activity tab when it is clicked', async () => {
        const user = userEvent.setup()
        const { onTabChange } = renderDetail()

        await user.click(await screen.findByRole('tab', { name: 'Activity' }))

        expect(onTabChange).toHaveBeenCalledExactlyOnceWith('activity')
    })
})
