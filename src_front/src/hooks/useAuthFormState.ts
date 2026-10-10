/** @file Shared submit handling for the login and registration forms. */

import { useNavigate } from 'react-router-dom'

import { useAuthStore } from '../store/auth'
import { useApiError } from './useApiError'

/**
 * Provide error state and a submit handler shared by both auth forms.
 *
 * @returns The current API error message, or null, and `handleAuthAction`,
 *   which runs an auth request and on success reloads the user into the store
 *   and navigates to `/`. On failure it records the error message in
 *   `apiError` instead of throwing.
 */
export function useAuthFormState() {
    const navigate = useNavigate()
    const fetchMe = useAuthStore((s) => s.fetchMe)
    const { error: apiError, onErr, clearError } = useApiError()

    /**
     * Run an auth request, then load the user and navigate on success.
     *
     * The client's interceptor has already copied any server error text into
     * the thrown `Error`; the fallback covers anything else that was thrown.
     *
     * @param action - The auth call to run, such as `login` or `register`.
     * @param fallback - Message to show when the thrown value is not an `Error`.
     */
    const handleAuthAction = async (action: () => Promise<unknown>, fallback: string) => {
        clearError()
        try {
            await action()
            await fetchMe()
            navigate('/')
        } catch (err: unknown) {
            onErr(err instanceof Error ? err : new Error(fallback))
        }
    }

    return { apiError, handleAuthAction }
}
