/** @file Delay a changing value until it has been stable for a moment. */

import { useEffect, useState } from 'react'

/**
 * Return the value only after it has stopped changing for `delayMs`.
 *
 * @param value - The live value, such as search text being typed.
 * @param delayMs - How long the value must hold still.
 * @returns The settled value.
 */
export function useDebouncedValue<T>(value: T, delayMs: number): T {
    const [settled, setSettled] = useState(value)

    useEffect(() => {
        const timer = setTimeout(() => setSettled(value), delayMs)
        return () => clearTimeout(timer)
    }, [value, delayMs])

    return settled
}
