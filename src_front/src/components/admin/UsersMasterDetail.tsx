/** @file The accounts as a master-detail page, the layout kit's example on Home. */

import AddIcon from '@mui/icons-material/Add'
import {
    Button,
    List,
    ListItem,
    ListItemButton,
    ListItemText,
    Typography,
} from '@mui/material'
import type { UseQueryResult } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'

import { useRecordDialogs } from '../../hooks/useRecordDialogs'
import { useSearchParamWriter } from '../../hooks/useSearchParamWriter'
import { useUserMutations, useUsers } from '../../hooks/users'
import type { User, UserPayload } from '../../types/users'
import type { CountNouns } from '../../utils/counts'
import { describeUser } from '../../utils/users'
import QueryState from '../common/QueryState'
import ListPaneHeader from '../layout/ListPaneHeader'
import MasterDetailLayout from '../layout/MasterDetailLayout'
import UserDetail from './UserDetail'
import UserFormDialog from './UserFormDialog'

/** The query parameter that holds the selected account's id. */
const SELECTED_PARAM = 'user'

/** The query parameter that holds the selected tab of the account's history. */
const TAB_PARAM = 'tab'

/** The nouns the account count reads with. */
const USER_NOUNS: CountNouns = { one: 'user', other: 'users' }

/** What the detail pane shows while no account is selected. */
const NO_SELECTION = (
    <Typography color="text.secondary" sx={{ p: 3 }}>
        Select a user to see their details.
    </Typography>
)

/** Props accepted by {@link UserRow}. */
interface UserRowProps {
    user: User
    selected: boolean
    onSelect: (id: number) => void
}

/** Props accepted by {@link UserListPane}. */
interface UserListPaneProps {
    query: UseQueryResult<User[]>
    selectedId: number | undefined
    onSelect: (id: number) => void
    onNew: () => void
}

/**
 * Render one account as a row that opens it, marked while it is open.
 *
 * @param props - The component props.
 * @returns The row.
 */
function UserRow(props: UserRowProps) {
    const { user, selected, onSelect } = props
    return (
        <ListItem disablePadding divider>
            <ListItemButton
                selected={selected}
                aria-current={selected ? 'true' : undefined}
                onClick={() => onSelect(user.id)}
            >
                <ListItemText primary={user.email} secondary={describeUser(user)} />
            </ListItemButton>
        </ListItem>
    )
}

/**
 * Render the account list: its heading, count, and New user, then a row per account.
 *
 * @param props - The component props.
 * @returns The list pane's content.
 */
function UserListPane(props: UserListPaneProps) {
    const { query, selectedId, onSelect, onNew } = props
    return (
        <>
            <ListPaneHeader
                title="Users"
                count={query.isError ? undefined : query.data?.length}
                nouns={USER_NOUNS}
                action={
                    <Button
                        size="small"
                        variant="contained"
                        startIcon={<AddIcon />}
                        onClick={onNew}
                    >
                        New user
                    </Button>
                }
            />
            <QueryState query={query}>
                {(users) => (
                    <List disablePadding>
                        {users.map((user) => (
                            <UserRow
                                key={user.id}
                                user={user}
                                selected={user.id === selectedId}
                                onSelect={onSelect}
                            />
                        ))}
                    </List>
                )}
            </QueryState>
        </>
    )
}

/**
 * Read the selected account and tab from the URL, with their writers.
 *
 * Selecting an account, or clearing the selection, pushes a history entry, so Back
 * returns from an account to the list; choosing a tab replaces the entry.
 *
 * @returns The selected id and tab as the URL holds them, and their writers.
 */
function useSelectionParams() {
    const [params] = useSearchParams()
    const writeSelection = useSearchParamWriter({ push: true })
    const writeTab = useSearchParamWriter()
    return {
        selectedId: params.get(SELECTED_PARAM),
        tab: params.get(TAB_PARAM) ?? '',
        select: (id: number | null) =>
            writeSelection(SELECTED_PARAM, id === null ? '' : String(id)),
        selectTab: (tab: string) => writeTab(TAB_PARAM, tab),
    }
}

/**
 * Hold the account dialog and save what it submits.
 *
 * @param select - Selects an account by id; a new account is selected once saved.
 * @returns The dialog state and the submit handler.
 */
function useUserForm(select: (id: number) => void) {
    const dialogs = useRecordDialogs<User>()
    const { create, update } = useUserMutations()

    /**
     * Create or update, depending on which dialog is open, then close it.
     *
     * The form dialog cannot be dismissed while this runs (see `RecordDialogProps`),
     * so the dialog still open when the save settles is the one that started it.
     *
     * @param payload - The validated request body.
     */
    const submit = async (payload: UserPayload) => {
        if (dialogs.editing) {
            await update.mutateAsync({ id: dialogs.editing.id, payload })
        } else {
            const created = await create.mutateAsync(payload)
            select(created.id)
        }
        dialogs.close()
    }

    return { dialogs, submit }
}

/**
 * Render the accounts beside the selected one, with the dialog that creates and edits
 * them.
 *
 * The selected account and tab live in the URL, as in `/?user=2&tab=activity`, so a
 * reload or a shared link shows the same view, and an id that matches no account
 * selects nothing. This is the layout kit's example; a project replaces it with its
 * own records.
 *
 * @returns The page content.
 */
export default function UsersMasterDetail() {
    const query = useUsers()
    const { selectedId, tab, select, selectTab } = useSelectionParams()
    const { dialogs, submit } = useUserForm(select)
    const selected = query.data?.find((user) => String(user.id) === selectedId) ?? null
    return (
        <>
            <MasterDetailLayout
                list={
                    <UserListPane
                        query={query}
                        selectedId={selected?.id}
                        onSelect={select}
                        onNew={dialogs.openCreate}
                    />
                }
                detail={
                    selected && (
                        <UserDetail
                            user={selected}
                            tab={tab}
                            onTabChange={selectTab}
                            onEdit={() => dialogs.openEdit(selected)}
                        />
                    )
                }
                showDetail={selected !== null}
                onBack={() => select(null)}
                emptyState={NO_SELECTION}
            />
            <UserFormDialog
                open={dialogs.creating || dialogs.editing !== null}
                item={dialogs.editing}
                onClose={dialogs.close}
                onSubmit={submit}
            />
        </>
    )
}
