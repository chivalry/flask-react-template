import DeleteIcon from '@mui/icons-material/Delete'
import EditIcon from '@mui/icons-material/Edit'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import EntityList from '../../../components/common/EntityList'
import type { EntityListProps } from '../../../components/common/EntityList'
import type { AuthUser } from '../../../types/auth'
import { adminUser, plainUser } from '../../utils/fixtures'

const onAdd = vi.fn()
const onEdit = vi.fn()
const onDelete = vi.fn()

const renderList = (overrides: Partial<EntityListProps<AuthUser>> = {}) =>
    render(
        <EntityList<AuthUser>
            title="Users"
            items={[adminUser, plainUser]}
            emptyText="No users yet."
            addLabel="New user"
            onAdd={onAdd}
            renderPrimary={(account) => account.email}
            actions={(account) => [
                { label: 'Edit', icon: <EditIcon />, onClick: () => onEdit(account.id) },
                {
                    label: 'Delete',
                    icon: <DeleteIcon />,
                    onClick: () => onDelete(account.id),
                },
            ]}
            {...overrides}
        />,
    )

describe('EntityList', () => {
    beforeEach(() => {
        vi.clearAllMocks()
    })

    it('renders the title as a heading', () => {
        renderList()

        expect(
            screen.getByRole('heading', { level: 2, name: 'Users' }),
        ).toBeInTheDocument()
    })

    it('calls onAdd when the Add button is clicked', async () => {
        const user = userEvent.setup()
        renderList()

        await user.click(screen.getByRole('button', { name: 'New user' }))

        expect(onAdd).toHaveBeenCalledTimes(1)
    })

    it('disables Add and explains why when given a reason', () => {
        renderList({ addDisabledReason: 'Add team members first.' })

        expect(screen.getByRole('button', { name: 'New user' })).toBeDisabled()
        expect(screen.getByText('Add team members first.')).toBeInTheDocument()
    })

    it('shows the empty text when there are no items', () => {
        renderList({ items: [] })

        expect(screen.getByText('No users yet.')).toBeInTheDocument()
        expect(screen.queryByRole('listitem')).not.toBeInTheDocument()
    })

    it('renders a row per item and no empty text', () => {
        renderList()

        expect(screen.getAllByRole('listitem')).toHaveLength(2)
        expect(screen.queryByText('No users yet.')).not.toBeInTheDocument()
    })

    it('renders each row with its primary and secondary text', () => {
        renderList({ renderSecondary: (account) => account.role })

        const [adminRow, plainRow] = screen.getAllByRole('listitem')
        expect(within(adminRow).getByText('admin@example.com')).toBeInTheDocument()
        expect(within(adminRow).getByText('admin')).toBeInTheDocument()
        expect(within(plainRow).getByText('user@example.com')).toBeInTheDocument()
        expect(within(plainRow).getByText('user')).toBeInTheDocument()
    })

    it('opens each run of one group with a subheader', () => {
        const thirdUser = { ...plainUser, id: 3, email: 'third@example.com' }
        renderList({
            items: [adminUser, plainUser, thirdUser],
            groupOf: (account) => (account.role === 'admin' ? 'Admins' : 'Members'),
        })

        expect(screen.getAllByRole('listitem').map((item) => item.textContent)).toEqual([
            'Admins',
            'admin@example.com',
            'Members',
            'user@example.com',
            'third@example.com',
        ])
    })

    it('renders no subheaders without groupOf', () => {
        renderList()

        expect(screen.getAllByRole('listitem').map((item) => item.textContent)).toEqual([
            'admin@example.com',
            'user@example.com',
        ])
    })

    it('renders no secondary text without renderSecondary', () => {
        renderList()

        expect(screen.getByText('admin@example.com')).toBeInTheDocument()
        expect(screen.queryByText('admin')).not.toBeInTheDocument()
    })

    it('renders each action as a labelled icon button calling its handler', async () => {
        const user = userEvent.setup()
        renderList()
        const [adminRow] = screen.getAllByRole('listitem')

        await user.click(within(adminRow).getByRole('button', { name: 'Edit' }))
        await user.click(within(adminRow).getByRole('button', { name: 'Delete' }))

        expect(onEdit).toHaveBeenCalledWith(adminUser.id)
        expect(onDelete).toHaveBeenCalledWith(adminUser.id)
        expect(within(adminRow).getByTestId('EditIcon')).toBeInTheDocument()
        expect(within(adminRow).getByTestId('DeleteIcon')).toBeInTheDocument()
    })
})
