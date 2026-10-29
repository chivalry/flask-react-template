/** @file Write one URL query parameter in place, keeping the others. */

import { useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'

/** How {@link useSearchParamWriter} records each write in the browser history. */
interface SearchParamWriterOptions {
    /** Push a history entry for each write, so Back returns to the previous value. */
    push?: boolean
}

/**
 * Return a function that writes one query parameter and keeps the others.
 *
 * An empty value deletes the parameter instead of leaving `key=` in the URL, and a
 * value the URL already holds writes nothing. By default every write replaces the
 * current history entry rather than pushing one, so Back leaves the page instead of
 * undoing one change at a time, as suits a filter typed a letter at a time. With
 * `push`, each write is an entry of its own, as suits a selection that Back should
 * undo, such as the record a master-detail page shows; clicking the record already
 * shown then adds no entry.
 *
 * @param options - How writes enter the history; by default they replace the entry.
 * @returns The writer, called with the parameter's name and its new value.
 */
export function useSearchParamWriter(options: SearchParamWriterOptions = {}) {
    const { push = false } = options
    const [params, setParams] = useSearchParams()
    return useCallback(
        (key: string, value: string) => {
            if ((params.get(key) ?? '') === value) return
            setParams(
                (current) => {
                    const next = new URLSearchParams(current)
                    if (value) next.set(key, value)
                    else next.delete(key)
                    return next
                },
                { replace: !push },
            )
        },
        [params, setParams, push],
    )
}
