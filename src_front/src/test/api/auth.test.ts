import { AxiosHeaders, type AxiosResponse } from 'axios'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { login, logout, me, register } from '../../api/auth'
import client from '../../api/client'
import { plainUser } from '../utils/fixtures'

vi.mock('../../api/client')

const mockedPost = vi.mocked(client.post)
const mockedGet = vi.mocked(client.get)

const buildAxiosResponse = <T>(data: T): AxiosResponse<T> => ({
    data,
    status: 200,
    statusText: 'OK',
    headers: new AxiosHeaders(),
    config: { headers: new AxiosHeaders() },
})

describe('auth api', () => {
    beforeEach(() => {
        vi.resetAllMocks()
    })

    it('register posts the email and password to /v1/auth/register', async () => {
        const response = buildAxiosResponse(plainUser)
        mockedPost.mockResolvedValue(response)

        await expect(register(plainUser.email, 'secret')).resolves.toBe(response)

        expect(mockedPost).toHaveBeenCalledTimes(1)
        expect(mockedPost).toHaveBeenCalledWith('/v1/auth/register', {
            email: plainUser.email,
            password: 'secret',
        })
    })

    it('login posts the email and password to /v1/auth/login', async () => {
        const response = buildAxiosResponse(plainUser)
        mockedPost.mockResolvedValue(response)

        await expect(login(plainUser.email, 'secret')).resolves.toBe(response)

        expect(mockedPost).toHaveBeenCalledTimes(1)
        expect(mockedPost).toHaveBeenCalledWith('/v1/auth/login', {
            email: plainUser.email,
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
        const response = buildAxiosResponse(plainUser)
        mockedGet.mockResolvedValue(response)

        await expect(me()).resolves.toBe(response)

        expect(mockedGet).toHaveBeenCalledTimes(1)
        expect(mockedGet).toHaveBeenCalledWith('/v1/auth/me')
    })
})
