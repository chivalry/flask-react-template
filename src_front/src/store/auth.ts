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
 * Access the signed-in user and the actions that change them.
 *
 * Nothing is persisted on the client: the server cookie is the session, and
 * `fetchMe` reconciles the store with it on page load. `isLoading` stays true
 * until that first reconciliation settles, so route guards can wait instead of
 * redirecting a signed-in visitor to the login page.
 */
export const useAuthStore = create<AuthState>()((set) => ({
    user: null,
    isLoading: true,
    setUser: (user) => set({ user }),
    clearUser: () => set({ user: null }),
    fetchMe: async () => {
        try {
            const { data } = await me()
            set({ user: data, isLoading: false })
        } catch {
            set({ user: null, isLoading: false })
        }
    },
    logout: async () => {
        try {
            await requestLogout()
        } finally {
            set({ user: null })
        }
    },
}))

// A 401 outside the auth endpoints means the session is gone: drop the user so
// the route guards send the visitor back to the login page.
setUnauthorizedHandler(() => useAuthStore.setState({ user: null, isLoading: false }))
