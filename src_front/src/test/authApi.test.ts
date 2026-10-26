import { AxiosHeaders, type AxiosResponse } from 'axios'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { login, logout, me, register } from '../api/auth'
import client from '../api/client'
import type { AuthUser } from '../types/auth'

vi.mock('../api/client')

const mockedPost = vi.mocked(client.post)
const mockedGet = vi.mocked(client.get)

const buildAxiosResponse = <T>(data: T): AxiosResponse<T> => ({
    data,
    status: 200,
    statusText: 'OK',
    headers: new AxiosHeaders(),
    config: { headers: new AxiosHeaders() },
})

const user: AuthUser = {
    id: 1,
    uuid: '5f0c7f0a-1111-2222-3333-444444444444',
    email: 'user@example.com',
    role: 'user',
    has_password: true,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
}

describe('auth api', () => {
    beforeEach(() => {
        vi.resetAllMocks()
    })

    it('register posts the email and password to /v1/auth/register', async () => {
        const response = buildAxiosResponse(user)
        mockedPost.mockResolvedValue(response)

        await expect(register('user@example.com', 'secret')).resolves.toBe(response)

        expect(mockedPost).toHaveBeenCalledTimes(1)
        expect(mockedPost).toHaveBeenCalledWith('/v1/auth/register', {
            email: 'user@example.com',
            password: 'secret',
        })
    })

    it('login posts the email and password to /v1/auth/login', async () => {
        const response = buildAxiosResponse(user)
        mockedPost.mockResolvedValue(response)

        await expect(login('user@example.com', 'secret')).resolves.toBe(response)

        expect(mockedPost).toHaveBeenCalledTimes(1)
        expect(mockedPost).toHaveBeenCalledWith('/v1/auth/login', {
            email: 'user@example.com',
            password: 'secret',
        })
    })

    it('logout posts to /v1/auth/logout', async () => {
        const response = buildAxiosResponse({ message: 'Logged out' })
        mockedPost.mockResolvedValue(response)

        await expect(logout()).resolves.toBe(response)

        expect(mockedPost).toHaveBeenCalledTimes(1)
        expect(mockedPost).toHaveBeenCalledWith('/v1/auth/logout')
    })

    it('me fetches the current user from /v1/auth/me', async () => {
        const response = buildAxiosResponse(user)
        mockedGet.mockResolvedValue(response)

        await expect(me()).resolves.toBe(response)

        expect(mockedGet).toHaveBeenCalledTimes(1)
        expect(mockedGet).toHaveBeenCalledWith('/v1/auth/me')
    })
})
