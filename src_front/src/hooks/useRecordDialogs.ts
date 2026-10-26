/** @file Open/closed state for one record list's create, edit, and delete dialogs. */

import { useState } from 'react'

/**
 * Track which dialog of a record list is open and for which record.
 *
 * @returns The current dialog state and the functions that change it.
 */
export function useRecordDialogs<T>() {
    const [creating, setCreating] = useState(false)
    const [editing, setEditing] = useState<T | null>(null)
    const [deleting, setDeleting] = useState<T | null>(null)

    /** Close whichever dialog is open. */
    const close = () => {
        setCreating(false)
        setEditing(null)
        setDeleting(null)
    }

    return {
        creating,
        editing,
        deleting,
        openCreate: () => setCreating(true),
        openEdit: (item: T) => setEditing(item),
        openDelete: (item: T) => setDeleting(item),
        close,
    }
}
