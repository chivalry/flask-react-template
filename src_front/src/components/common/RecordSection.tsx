/** @file A record list with its create, edit, and delete dialogs wired to mutations. */

import DeleteIcon from '@mui/icons-material/Delete'
import EditIcon from '@mui/icons-material/Edit'
import type { ReactNode } from 'react'

import { useRecordDialogs } from '../../hooks/useRecordDialogs'
import ConfirmDialog from './ConfirmDialog'
import EntityList from './EntityList'
import type { EntityAction } from './EntityList'

/** A mutation that deletes a record by id, such as a TanStack `useMutation` result. */
interface RemoveMutation {
    mutateAsync: (id: number) => Promise<unknown>
}

/** The mutations a record list drives; without `remove`, no row offers Delete. */
interface RecordMutations<T, P> {
    create: { mutateAsync: (payload: P) => Promise<T> }
    update: { mutateAsync: (args: { id: number; payload: P }) => Promise<T> }
    remove?: RemoveMutation
}

/** What a record's form dialog receives from {@link RecordSection}. */
export interface RecordDialogProps<T, P> {
    open: boolean
    item: T | null
    onClose: () => void
    onSubmit: (payload: P) => Promise<void>
}

/** Props accepted by {@link RecordSection}. */
interface RecordSectionProps<T extends { id: number }, P> {
    title: string
    addLabel: string
    emptyText: string
    items: T[]
    mutations: RecordMutations<T, P>
    renderPrimary: (item: T) => ReactNode
    renderSecondary?: (item: T) => ReactNode
    /** Decides whether a row offers Delete; every row does when `remove` is given. */
    canDelete?: (item: T) => boolean
    /** The delete confirmation's title; defaults to "Delete record". */
    deleteTitle?: string
    /** The delete confirmation's text for a record; defaults to a permanence warning. */
    deleteMessage?: (item: T) => string
    renderDialog: (dialog: RecordDialogProps<T, P>) => ReactNode
    /** Why Add is disabled; Add is enabled without it. */
    addDisabledReason?: string
    /** Names each item's group; a subheader opens each run of one group. */
    groupOf?: (item: T) => string
}

/** Props accepted by {@link RecordDeleteDialog}. */
interface RecordDeleteDialogProps<T extends { id: number }> {
    item: T | null
    remove: RemoveMutation
    title?: string
    message?: (item: T) => string
    onClose: () => void
}

/**
 * Warn that a delete is permanent, for lists that pass no message of their own.
 *
 * @returns The warning.
 */
const permanenceWarning = () => 'This cannot be undone.'

/**
 * Ask before deleting the selected record, then delete it and close.
 *
 * @param props - The component props.
 * @returns The confirmation, open while a record is selected.
 */
function RecordDeleteDialog<T extends { id: number }>(props: RecordDeleteDialogProps<T>) {
    const {
        item,
        remove,
        title = 'Delete record',
        message = permanenceWarning,
        onClose,
    } = props

    /** Delete the selected record, then close the confirmation. */
    const confirm = async () => {
        // Delete is clickable only while open, and the dialog is open only with an item.
        await remove.mutateAsync(item!.id)
        onClose()
    }

    return (
        <ConfirmDialog
            open={item !== null}
            title={title}
            message={item ? message(item) : ''}
            onCancel={onClose}
            onConfirm={confirm}
        />
    )
}

/**
 * Hold the dialog state and the handlers that connect it to the mutations.
 *
 * @param mutations - The record list's mutations.
 * @param canDelete - Decides whether a row offers Delete when the list can delete;
 *   every row does by default.
 * @returns The dialog state, the submit handler, and the row actions.
 */
function useRecordHandlers<T extends { id: number }, P>(
    mutations: RecordMutations<T, P>,
    canDelete?: (item: T) => boolean,
) {
    const dialogs = useRecordDialogs<T>()

    /**
     * Create or update, depending on which dialog is open, then close it.
     *
     * @param payload - The validated request body.
     */
    const submit = async (payload: P) => {
        if (dialogs.editing) {
            await mutations.update.mutateAsync({ id: dialogs.editing.id, payload })
        } else {
            await mutations.create.mutateAsync(payload)
        }
        dialogs.close()
    }

    /**
     * Build the Edit and (when allowed) Delete actions for a row.
     *
     * @param item - The row's record.
     * @returns The actions.
     */
    const actions = (item: T): EntityAction[] => {
        const list = [
            { label: 'Edit', icon: <EditIcon />, onClick: () => dialogs.openEdit(item) },
        ]
        if (mutations.remove && (canDelete?.(item) ?? true)) {
            list.push({
                label: 'Delete',
                icon: <DeleteIcon />,
                onClick: () => dialogs.openDelete(item),
            })
        }
        return list
    }

    return { dialogs, submit, actions }
}

/**
 * Render a record list whose Add, Edit, and Delete controls drive the given
 * dialogs and mutations.
 *
 * @param props - The component props.
 * @returns The list, the form dialog, and, given `remove`, the delete confirmation.
 */
export default function RecordSection<T extends { id: number }, P>(
    props: RecordSectionProps<T, P>,
) {
    const {
        mutations,
        canDelete,
        renderDialog,
        deleteMessage,
        deleteTitle,
        ...listProps
    } = props
    const { dialogs, submit, actions } = useRecordHandlers(mutations, canDelete)
    return (
        <>
            <EntityList {...listProps} onAdd={dialogs.openCreate} actions={actions} />
            {renderDialog({
                open: dialogs.creating || dialogs.editing !== null,
                item: dialogs.editing,
                onClose: dialogs.close,
                onSubmit: submit,
            })}
            {mutations.remove && (
                <RecordDeleteDialog
                    item={dialogs.deleting}
                    remove={mutations.remove}
                    title={deleteTitle}
                    message={deleteMessage}
                    onClose={dialogs.close}
                />
            )}
        </>
    )
}
