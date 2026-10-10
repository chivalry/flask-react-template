import { AxiosError, AxiosHeaders } from 'axios'
import type { AxiosAdapter, AxiosResponse, InternalAxiosRequestConfig } from 'axios'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { logout, me } from '../api/auth'
import client from '../api/client'
import { useAuthStore } from '../store/auth'
import type { AuthUser } from '../types/auth'

vi.mock('../api/auth')

const testUser: AuthUser = {
    id: 1,
    uuid: 'user-uuid-1',
    email: 'tester@example.com',
    role: 'admin',
    created_at: '2026-08-01T00:00:00Z',
    updated_at: '2026-08-01T00:00:00Z',
}

// An adapter standing in for the network: every request is refused with 401.
const refuseWith401: AxiosAdapter = async (config: InternalAxiosRequestConfig) => {
    const response: AxiosResponse = {
        data: { error: 'Session expired.' },
        status: 401,
        statusText: '',
        headers: new AxiosHeaders(),
        config,
    }
    throw new AxiosError('Unauthorized', 'ERR_BAD_REQUEST', config, undefined, response)
}

describe('useAuthStore', () => {
    beforeEach(() => {
        vi.clearAllMocks()
        useAuthStore.setState({ user: null, isLoading: false })
    })

    it('starts with no user and the loading flag raised', () => {
        const { user, isLoading } = useAuthStore.getInitialState()

        expect(user).toBeNull()
        expect(isLoading).toBe(true)
    })

    it('setUser stores the user', () => {
        useAuthStore.getState().setUser(testUser)

        expect(useAuthStore.getState().user).toEqual(testUser)
    })

    it('clearUser resets the user to null', () => {
        useAuthStore.getState().setUser(testUser)

        useAuthStore.getState().clearUser()

        expect(useAuthStore.getState().user).toBeNull()
    })

    describe('fetchMe', () => {
        it('stores the user and lowers the loading flag on success', async () => {
            useAuthStore.setState({ isLoading: true })
            vi.mocked(me).mockResolvedValue({ data: testUser } as AxiosResponse<AuthUser>)

            await useAuthStore.getState().fetchMe()

            expect(me).toHaveBeenCalledTimes(1)
            expect(useAuthStore.getState()).toMatchObject({
                user: testUser,
                isLoading: false,
            })
        })

        it('clears the user and lowers the loading flag on failure', async () => {
            useAuthStore.setState({ user: testUser, isLoading: true })
            vi.mocked(me).mockRejectedValue(new Error('Unauthorized'))

            await useAuthStore.getState().fetchMe()

            expect(useAuthStore.getState()).toMatchObject({
                user: null,
                isLoading: false,
            })
        })
    })

    describe('logout', () => {
        it('calls the API and clears the user', async () => {
            useAuthStore.setState({ user: testUser })
            vi.mocked(logout).mockResolvedValue({
                data: { message: 'Logged out' },
            } as AxiosResponse<{ message: string }>)

            await useAuthStore.getState().logout()

            expect(logout).toHaveBeenCalledTimes(1)
            expect(useAuthStore.getState().user).toBeNull()
        })

        it('clears the user even when the request fails, then rethrows', async () => {
            useAuthStore.setState({ user: testUser })
            vi.mocked(logout).mockRejectedValue(new Error('logout request failed'))

            await expect(useAuthStore.getState().logout()).rejects.toThrow(
                'logout request failed',
            )

            expect(useAuthStore.getState().user).toBeNull()
        })
    })

    describe('lost-session handler', () => {
        it('drops the user when a request outside the auth endpoints gets a 401', async () => {
            useAuthStore.setState({ user: testUser, isLoading: true })

            await expect(
                client.get('/v1/things', { adapter: refuseWith401 }),
            ).rejects.toThrow('Session expired.')

            expect(useAuthStore.getState()).toMatchObject({
                user: null,
                isLoading: false,
            })
        })
    })
})
