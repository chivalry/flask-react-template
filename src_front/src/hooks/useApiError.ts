/** @file Error-message state for components that call the API. */

import { useState } from 'react'

/**
 * Hold the message of the last failed API call for display in an alert.
 *
 * The client's response interceptor already copies the server's `{ error }`
 * text into `error.message`, so an `Error` is shown as is; any other thrown
 * value falls back to the default message.
 *
 * @param defaultMessage - Text shown when the thrown value is not an `Error`.
 * @returns The current message or null, `onErr` to record a failure, and
 *   `clearError` to dismiss it.
 */
export function useApiError(defaultMessage = 'An unexpected error occurred.') {
    const [error, setError] = useState<string | null>(null)

    /**
     * Record a failed call so its message can be shown.
     *
     * @param err - The value the failed call threw.
     */
    const onErr = (err: unknown) => {
        setError(err instanceof Error ? err.message : defaultMessage)
    }

    /** Dismiss the current message. */
    const clearError = () => {
        setError(null)
    }

    return { error, onErr, clearError }
}
