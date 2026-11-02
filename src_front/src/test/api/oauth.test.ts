/** @file The provider endpoints target `/v1/auth/oauth` and unwrap their bodies. */

import { AxiosHeaders, type AxiosResponse } from 'axios'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import client from '../../api/client'
import { listLinkedAccounts, listProviders, unlinkAccount } from '../../api/oauth'
import { googleProvider, linkedGoogleAccount } from '../utils/fixtures'

vi.mock('../../api/client')

const mockedGet = vi.mocked(client.get)
const mockedDelete = vi.mocked(client.delete)

const buildAxiosResponse = <T>(data: T): AxiosResponse<T> => ({
    data,
    status: 200,
    statusText: 'OK',
    headers: new AxiosHeaders(),
    config: { headers: new AxiosHeaders() },
})

describe('oauth api', () => {
    beforeEach(() => {
        vi.resetAllMocks()
    })

    it('listProviders gets /v1/auth/oauth/providers and returns the list', async () => {
        mockedGet.mockResolvedValue(buildAxiosResponse([googleProvider]))

        await expect(listProviders()).resolves.toEqual([googleProvider])

        expect(mockedGet).toHaveBeenCalledTimes(1)
        expect(mockedGet).toHaveBeenCalledWith('/v1/auth/oauth/providers')
    })

    it('listLinkedAccounts gets /v1/auth/oauth/accounts and returns them', async () => {
        mockedGet.mockResolvedValue(buildAxiosResponse([linkedGoogleAccount]))

        await expect(listLinkedAccounts()).resolves.toEqual([linkedGoogleAccount])

        expect(mockedGet).toHaveBeenCalledTimes(1)
        expect(mockedGet).toHaveBeenCalledWith('/v1/auth/oauth/accounts')
    })

    it('unlinkAccount deletes the provider under /v1/auth/oauth/accounts', async () => {
        mockedDelete.mockResolvedValue(buildAxiosResponse(''))

        await expect(unlinkAccount('google')).resolves.toBeUndefined()

        expect(mockedDelete).toHaveBeenCalledTimes(1)
        expect(mockedDelete).toHaveBeenCalledWith('/v1/auth/oauth/accounts/google')
    })

    it('unlinkAccount encodes the provider name into one path segment', async () => {
        mockedDelete.mockResolvedValue(buildAxiosResponse(''))

        await unlinkAccount('a/b c?')

        expect(mockedDelete).toHaveBeenCalledWith('/v1/auth/oauth/accounts/a%2Fb%20c%3F')
    })
})
