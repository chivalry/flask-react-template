/** @file Shared submit handling for the login and registration forms. */

import type { AxiosResponse } from 'axios'
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom'

import { useAuthStore } from '../store/auth'
import type { AuthUser } from '../types/auth'
import { oauthErrorMessage } from '../utils/oauth'
import { useApiError } from './useApiError'

/** What `ProtectedRoute` records about the page a signed-out visitor asked for. */
interface RedirectState {
    from?: { pathname?: string; search?: string; hash?: string }
}

/**
 * Find where to go after signing in.
 *
 * @param state - The login page's location state.
 * @returns The requested path with its query and hash, or `/` without one.
 */
function requestedPath(state: unknown): string {
    const from = (state as RedirectState | null)?.from
    if (!from?.pathname) return '/'
    return `${from.pathname}${from.search ?? ''}${from.hash ?? ''}`
}

/**
 * Provide error state and a submit handler shared by both auth forms.
 *
 * @returns The current API error message, which falls back on the message for the
 *   `error` parameter a failed provider sign-in redirects with, or null;
 *   `handleAuthAction`, which runs an auth request, stores the user it returns, and
 *   navigates to the requested page, or to `/` when none was recorded, and on failure
 *   records the error message in `apiError` instead of throwing; and `returnPath`,
 *   where a provider sign-in should come back to.
 */
export function useAuthFormState() {
    const navigate = useNavigate()
    const location = useLocation()
    const [params] = useSearchParams()
    const setUser = useAuthStore((s) => s.setUser)
    const { error: apiError, onErr, clearError } = useApiError()

    /**
     * Run an auth request, then store the returned user and navigate.
     *
     * The register and login endpoints both answer with the signed-in user, so
     * the store is filled from that response rather than from a second `/me`
     * round trip that could fail or race the page-load reconciliation. The
     * client's interceptor has already copied any server error text into the
     * thrown `Error`; the fallback covers anything else that was thrown. An action
     * that resolves null was cancelled, as a dismissed passkey prompt is, and leaves
     * the page as it was.
     *
     * @param action - The auth call to run, such as `login` or `register`.
     * @param fallback - Message to show when the thrown value is not an `Error`.
     */
    const handleAuthAction = async (
        action: () => Promise<AxiosResponse<AuthUser> | null>,
        fallback: string,
    ) => {
        clearError()
        try {
            const response = await action()
            if (response === null) return
            setUser(response.data)
            navigate(requestedPath(location.state))
        } catch (err: unknown) {
            onErr(err instanceof Error ? err : new Error(fallback))
        }
    }

    return {
        apiError: apiError ?? oauthErrorMessage(params.get('error')),
        handleAuthAction,
        returnPath: requestedPath(location.state),
    }
}
