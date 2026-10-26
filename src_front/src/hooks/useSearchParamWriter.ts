/** @file Write one URL query parameter in place, keeping the others. */

import { useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'

/**
 * Return a function that writes one query parameter and keeps the others.
 *
 * An empty value deletes the parameter instead of leaving `key=` in the URL. Every
 * write replaces the current history entry rather than pushing one, so Back leaves
 * the page instead of undoing one change at a time.
 *
 * @returns The writer, called with the parameter's name and its new value.
 */
export function useSearchParamWriter() {
    const [, setParams] = useSearchParams()
    return useCallback(
        (key: string, value: string) => {
            setParams(
                (current) => {
                    const next = new URLSearchParams(current)
                    if (value) next.set(key, value)
                    else next.delete(key)
                    return next
                },
                { replace: true },
            )
        },
        [setParams],
    )
}
