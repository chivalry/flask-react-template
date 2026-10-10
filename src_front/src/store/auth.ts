/** @file Auth store: the signed-in user, reconciled with the server session on load. */

import { create } from 'zustand'

import { logout as requestLogout, me } from '../api/auth'
import { setUnauthorizedHandler } from '../api/client'
import type { AuthUser } from '../types/auth'

/** The signed-in user, the initial-load flag, and the actions that change them. */
interface AuthState {
    user: AuthUser | null
    isLoading: boolean
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
 * Access the signed-in user and the actions that change them.
 *
 * Nothing is persisted on the client: the server cookie is the session, and
 * `fetchMe` reconciles the store with it on page load. `isLoading` stays true
 * until that reconciliation settles or a sign-in sets the user, so route guards
 * can wait instead of redirecting a signed-in visitor to the login page.
 */
export const useAuthStore = create<AuthState>()((set) => {
    /**
     * Record a settled user state and invalidate any `/me` request in flight.
     *
     * @param user - The signed-in user, or null when there is no session.
     */
    const settle = (user: AuthUser | null) => {
        generation += 1
        set({ user, isLoading: false })
    }

    return {
        user: null,
        isLoading: true,
        setUser: settle,
        clearUser: () => settle(null),
        fetchMe: async () => {
            const stamp = ++generation
            const user = await me().then(
                (response) => response.data,
                () => null,
            )
            if (stamp === generation) set({ user, isLoading: false })
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
