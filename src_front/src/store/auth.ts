/** @file Auth store: the signed-in user, reconciled with the server session on load. */

import axios from 'axios'
import { create } from 'zustand'

import { logout as requestLogout, me } from '../api/auth'
import { setUnauthorizedHandler } from '../api/client'
import type { AuthUser } from '../types/auth'

/** The signed-in user, the session-check flags, and the actions that change them. */
interface AuthState {
    user: AuthUser | null
    isLoading: boolean
    sessionCheckFailed: boolean
    setUser: (user: AuthUser) => void
    clearUser: () => void
    fetchMe: () => Promise<void>
    logout: () => Promise<void>
}

/**
 * Stamp for `fetchMe` calls, bumped by every explicit change to the user, so a
 * `/me` response that was still in flight when the visitor signed in or out is
 * recognized as stale and discarded instead of overwriting the newer state.
 */
let generation = 0

/**
 * Tell a confirmed "no session" answer apart from every other `/me` failure.
 *
 * Only a 401 proves the visitor is signed out. A network error, a timeout, or
 * a 5xx during a backend restart says nothing about the session, so those must
 * not log anyone out.
 *
 * @param error - The rejection from the `/me` request.
 * @returns Whether the server answered 401.
 */
const isUnauthorized = (error: unknown): boolean =>
    axios.isAxiosError(error) && error.response?.status === 401

/**
 * Access the signed-in user and the actions that change them.
 *
 * Nothing is persisted on the client: the server cookie is the session, and
 * `fetchMe` reconciles the store with it on page load. `isLoading` stays true
 * until that reconciliation settles or a sign-in sets the user, so route guards
 * can wait instead of redirecting a signed-in visitor to the login page.
 * `sessionCheckFailed` is raised when `/me` failed for a reason other than a
 * 401, so the guard can offer a retry instead of a redirect.
 */
export const useAuthStore = create<AuthState>()((set) => {
    /**
     * Record a settled user state and invalidate any `/me` request in flight.
     *
     * @param user - The signed-in user, or null when there is no session.
     */
    const settle = (user: AuthUser | null) => {
        generation += 1
        set({ user, isLoading: false, sessionCheckFailed: false })
    }

    return {
        user: null,
        isLoading: true,
        sessionCheckFailed: false,
        setUser: settle,
        clearUser: () => settle(null),
        fetchMe: async () => {
            const stamp = ++generation
            const result = await me().then(
                (response) => ({ user: response.data, sessionCheckFailed: false }),
                (error: unknown) =>
                    isUnauthorized(error)
                        ? { user: null, sessionCheckFailed: false }
                        : { sessionCheckFailed: true },
            )
            if (stamp === generation) set({ ...result, isLoading: false })
        },
        logout: async () => {
            try {
                await requestLogout()
            } catch {
                // The local session ends regardless; a server session that outlived
                // this failure is replaced the next time the visitor signs in.
            } finally {
                settle(null)
            }
        },
    }
})

// A 401 outside the auth endpoints means the session is gone: drop the user so
// the route guards send the visitor back to the login page.
setUnauthorizedHandler(() => useAuthStore.getState().clearUser())
