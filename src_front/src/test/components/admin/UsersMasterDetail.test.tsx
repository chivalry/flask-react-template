/** @file The accounts page lists accounts beside the open one, which the URL holds. */

import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { fetchAuditLogPage, fetchRecordHistoryPage } from '../../../api/auditLogs'
import { usersApi } from '../../../api/users'
import UsersMasterDetail from '../../../components/admin/UsersMasterDetail'
import { useAuthStore } from '../../../store/auth'
import type { User } from '../../../types/users'
import { findDialog } from '../../utils/dialogQueries'
import { adminUser, auditPage, plainUser } from '../../utils/fixtures'
import LocationProbe from '../../utils/LocationProbe'
import { renderWithProviders } from '../../utils/renderWithProviders'
import { stubViewportWidth } from '../../utils/viewport'

vi.mock('../../../api/users')
vi.mock('../../../api/auditLogs')

type UserSession = ReturnType<typeof userEvent.setup>

const newUser: User = {
    ...plainUser,
    id: 3,
    uuid: 'user-uuid-3',
    email: 'new@example.com',
}

/** Render the example on `route`, beside a probe of the router's location. */
const renderAccounts = (route = '/') =>
    renderWithProviders(
        <>
            <UsersMasterDetail />
            <LocationProbe />
        </>,
        { route },
    )

/** Read one of the location probe's outputs. */
const probe = (label: string) => screen.getByLabelText(label).textContent

/** The account count: the one status region the probe's named outputs leave. */
const accountCount = () => screen.getByRole('status', { name: '' })

/** The list row that opens the account with the given email. */
const rowFor = (email: string) => screen.getByRole('button', { name: new RegExp(email) })

/** The level-1 heading of the open account, or the list's own `Users`. */
const findHeading = (name: string) => screen.findByRole('heading', { level: 1, name })

/** Wait for the list, click the row with the given email, and wait for its detail. */
const openAccount = async (user: UserSession, email: string) => {
    await screen.findByText(email)
    await user.click(rowFor(email))
    return findHeading(email)
}

/** Click New user and wait for its dialog. */
const openNewUserDialog = async (user: UserSession) => {
    await user.click(screen.getByRole('button', { name: 'New user' }))
    return findDialog()
}

/** Open New user, fill in `newUser`'s email and a password, and save. */
const saveNewAccount = async (user: UserSession) => {
    const dialog = await openNewUserDialog(user)
    await user.type(dialog.getByLabelText('Email'), newUser.email)
    await user.type(dialog.getByLabelText('Password'), 'longenough')
    await user.click(dialog.getByRole('button', { name: 'Save' }))
}

describe('UsersMasterDetail', () => {
    beforeEach(() => {
        vi.clearAllMocks()
        useAuthStore.setState({ user: adminUser, isLoading: false })
        vi.mocked(usersApi.list).mockResolvedValue([adminUser, plainUser])
        vi.mocked(fetchRecordHistoryPage).mockResolvedValue(auditPage([]))
        vi.mocked(fetchAuditLogPage).mockResolvedValue(auditPage([]))
    })

    it('lists the accounts, counted, beside a prompt to select one', async () => {
        renderAccounts()

        expect(await screen.findByText(adminUser.email)).toBeInTheDocument()
        expect(screen.getByText(plainUser.email)).toBeInTheDocument()
        expect(await findHeading('Users')).toBeInTheDocument()
        expect(accountCount()).toHaveTextContent('2 users')
        expect(screen.getByText('Select a user to see their details.')).toBeVisible()
        expect(rowFor(adminUser.email).closest('li')).not.toBeNull()
        expect(rowFor(plainUser.email).closest('li')).not.toBeNull()
        expect(within(rowFor(adminUser.email)).getByText('admin')).toBeInTheDocument()
        expect(within(rowFor(plainUser.email)).getByText('user')).toBeInTheDocument()
    })

    it('opens a clicked account, pushing its id and marking its row', async () => {
        const user = userEvent.setup()
        renderAccounts()

        await openAccount(user, plainUser.email)

        expect(probe('Search')).toBe('?user=2')
        expect(probe('Navigation type')).toBe('PUSH')
        expect(rowFor(plainUser.email)).toHaveAttribute('aria-current', 'true')
        expect(rowFor(adminUser.email)).not.toHaveAttribute('aria-current')
    })

    it('opens the account and tab that a link names', async () => {
        renderAccounts('/?user=2&tab=activity')

        expect(await findHeading(plainUser.email)).toBeInTheDocument()
        expect(screen.getByRole('tab', { name: 'Activity' })).toHaveAttribute(
            'aria-selected',
            'true',
        )
    })

    it('records a chosen tab in the URL by replacing the history entry', async () => {
        const user = userEvent.setup()
        renderAccounts('/?user=2')
        await findHeading(plainUser.email)

        await user.click(screen.getByRole('tab', { name: 'Activity' }))

        expect(probe('Search')).toBe('?user=2&tab=activity')
        expect(probe('Navigation type')).toBe('REPLACE')
    })

    it.each(['/?user=99', '/?user=abc'])('selects no account for %s', async (route) => {
        renderAccounts(route)

        expect(await screen.findByText(plainUser.email)).toBeInTheDocument()
        expect(screen.getByText('Select a user to see their details.')).toBeVisible()
        const headings = screen.getAllByRole('heading', { level: 1 })
        expect(headings.map((heading) => heading.textContent)).toEqual(['Users'])
    })

    describe('at 375 px', () => {
        beforeEach(() => {
            stubViewportWidth(375)
        })

        it('swaps the list for the account, and Back returns to the list', async () => {
            const user = userEvent.setup()
            renderAccounts()

            await openAccount(user, plainUser.email)

            expect(screen.getByText('Users')).not.toBeVisible()

            await user.click(screen.getByRole('button', { name: 'Back' }))

            expect(screen.getByText('Users')).toBeVisible()
            expect(probe('Search')).toBe('')
            expect(probe('Navigation type')).toBe('PUSH')
        })

        it('moves focus to the detail pane when a linked account loads', async () => {
            renderAccounts('/?user=2')

            const heading = await findHeading(plainUser.email)

            expect(heading.closest('[tabindex="-1"]')).toHaveFocus()
        })
    })

    it('selects a new account once it is saved', async () => {
        const user = userEvent.setup()
        vi.mocked(usersApi.list)
            .mockResolvedValueOnce([adminUser, plainUser])
            .mockResolvedValue([adminUser, plainUser, newUser])
        vi.mocked(usersApi.create).mockResolvedValue(newUser)
        renderAccounts()
        await screen.findByText(plainUser.email)

        await saveNewAccount(user)

        expect(await findHeading(newUser.email)).toBeInTheDocument()
        expect(probe('Search')).toBe('?user=3')
        await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    })

    it('empties the count while a refetch has failed, as the alert shows', async () => {
        const user = userEvent.setup()
        vi.mocked(usersApi.list)
            .mockResolvedValueOnce([adminUser, plainUser])
            .mockRejectedValue(new Error('Network down'))
        vi.mocked(usersApi.create).mockResolvedValue(newUser)
        renderAccounts()
        await screen.findByText(plainUser.email)
        expect(accountCount()).toHaveTextContent('2 users')

        await saveNewAccount(user)

        expect(await screen.findByRole('alert')).toHaveTextContent('Network down')
        expect(accountCount()).toBeEmptyDOMElement()
    })

    it('edits the open account through the form dialog', async () => {
        const user = userEvent.setup()
        vi.mocked(usersApi.update).mockResolvedValue(plainUser)
        renderAccounts('/?user=2')
        await findHeading(plainUser.email)

        await user.click(screen.getByRole('button', { name: 'Edit' }))
        const dialog = await findDialog()
        expect(dialog.getByRole('heading', { name: 'Edit user' })).toBeInTheDocument()
        await user.clear(dialog.getByLabelText('Email'))
        await user.type(dialog.getByLabelText('Email'), 'renamed@example.com')
        await user.click(dialog.getByRole('button', { name: 'Save' }))

        await waitFor(() =>
            expect(usersApi.update).toHaveBeenCalledWith(
                2,
                expect.objectContaining({ email: 'renamed@example.com' }),
            ),
        )
        await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    })

    it('closes the dialog without saving when it is cancelled', async () => {
        const user = userEvent.setup()
        renderAccounts()
        await screen.findByText(plainUser.email)

        const dialog = await openNewUserDialog(user)
        await user.click(dialog.getByRole('button', { name: 'Cancel' }))

        await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
        expect(usersApi.create).not.toHaveBeenCalled()
    })

    it('leaves the count empty while the list is pending', () => {
        vi.mocked(usersApi.list).mockReturnValue(new Promise(() => undefined))
        renderAccounts()

        expect(screen.getByRole('progressbar')).toBeInTheDocument()
        expect(accountCount()).toBeEmptyDOMElement()
    })

    it('leaves the count empty when the list fails, and shows why', async () => {
        vi.mocked(usersApi.list).mockRejectedValue(new Error('Network down'))
        renderAccounts()

        expect(await screen.findByRole('alert')).toHaveTextContent('Network down')
        expect(accountCount()).toBeEmptyDOMElement()
    })
})
