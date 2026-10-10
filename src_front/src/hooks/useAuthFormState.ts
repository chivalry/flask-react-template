/** @file Shared submit handling for the login and registration forms. */

import type { AxiosResponse } from 'axios'
import { useNavigate } from 'react-router-dom'

import { useAuthStore } from '../store/auth'
import type { AuthUser } from '../types/auth'
import { useApiError } from './useApiError'

/**
 * Provide error state and a submit handler shared by both auth forms.
 *
 * @returns The current API error message, or null, and `handleAuthAction`,
 *   which runs an auth request, stores the user it returns, and navigates to
 *   `/`. On failure it records the error message in `apiError` instead of
 *   throwing.
 */
export function useAuthFormState() {
    const navigate = useNavigate()
    const setUser = useAuthStore((s) => s.setUser)
    const { error: apiError, onErr, clearError } = useApiError()

    /**
     * Run an auth request, then store the returned user and navigate.
     *
     * The register and login endpoints both answer with the signed-in user, so
     * the store is filled from that response rather than from a second `/me`
     * round trip that could fail or race the page-load reconciliation. The
     * client's interceptor has already copied any server error text into the
     * thrown `Error`; the fallback covers anything else that was thrown.
     *
     * @param action - The auth call to run, such as `login` or `register`.
     * @param fallback - Message to show when the thrown value is not an `Error`.
     */
    const handleAuthAction = async (
        action: () => Promise<AxiosResponse<AuthUser>>,
        fallback: string,
    ) => {
        clearError()
        try {
            const { data: user } = await action()
            setUser(user)
            navigate('/')
        } catch (err: unknown) {
            onErr(err instanceof Error ? err : new Error(fallback))
        }
    }

    return { apiError, handleAuthAction }
}
