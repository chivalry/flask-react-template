/** @file The passkey endpoints target `/v1/auth/passkeys`; an Add runs the prompt. */

import { startRegistration } from '@simplewebauthn/browser'
import type { AxiosResponse } from 'axios'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import client from '../../api/client'
import { loginOptions, loginVerify, passkeysApi } from '../../api/passkeys'
import type { AuthUser, Passkey } from '../../types/auth'
import { laptopPasskey, plainUser } from '../utils/fixtures'
import {
    authenticationResponse,
    ceremonyError,
    creationOptions,
    registrationResponse,
    requestOptions,
} from '../utils/webauthn'

vi.mock('@simplewebauthn/browser', async (importOriginal) =>
    (await import('../utils/webauthnMock')).mockWebAuthnBrowser(importOriginal),
)
vi.mock('../../api/client')

const mockedGet = vi.mocked(client.get)
const mockedPost = vi.mocked(client.post)

/** The passkey the server saves for an Add named Phone. */
const phonePasskey: Passkey = { ...laptopPasskey, id: 4, nickname: 'Phone' }

describe('passkeysApi', () => {
    beforeEach(() => {
        vi.resetAllMocks()
    })

    it('list gets /v1/auth/passkeys and returns the passkeys', async () => {
        mockedGet.mockResolvedValue({ data: [laptopPasskey] })

        await expect(passkeysApi.list()).resolves.toEqual([laptopPasskey])

        expect(mockedGet).toHaveBeenCalledExactlyOnceWith('/v1/auth/passkeys')
    })

    it('update puts the payload to the passkey path', async () => {
        vi.mocked(client.put).mockResolvedValue({ data: laptopPasskey })

        await expect(passkeysApi.update(3, { nickname: 'Laptop' })).resolves.toBe(
            laptopPasskey,
        )

        expect(client.put).toHaveBeenCalledExactlyOnceWith('/v1/auth/passkeys/3', {
            nickname: 'Laptop',
        })
    })

    it('remove deletes the passkey path', async () => {
        vi.mocked(client.delete).mockResolvedValue({ data: '' })

        await expect(passkeysApi.remove(3)).resolves.toBeUndefined()

        expect(client.delete).toHaveBeenCalledExactlyOnceWith('/v1/auth/passkeys/3')
    })

    it('create gets the options, runs the prompt, and saves what it made', async () => {
        mockedGet.mockResolvedValue({ data: creationOptions })
        vi.mocked(startRegistration).mockResolvedValue(registrationResponse)
        mockedPost.mockResolvedValue({ data: phonePasskey })

        await expect(passkeysApi.create({ nickname: 'Phone' })).resolves.toBe(
            phonePasskey,
        )

        expect(mockedGet).toHaveBeenCalledExactlyOnceWith(
            '/v1/auth/passkeys/register/options',
        )
        expect(startRegistration).toHaveBeenCalledExactlyOnceWith({
            optionsJSON: creationOptions,
        })
        expect(mockedPost).toHaveBeenCalledExactlyOnceWith(
            '/v1/auth/passkeys/register/verify',
            { credential: registrationResponse, nickname: 'Phone' },
        )
    })

    it('create rejects a dismissed prompt as cancelled and saves nothing', async () => {
        mockedGet.mockResolvedValue({ data: creationOptions })
        vi.mocked(startRegistration).mockRejectedValue(
            ceremonyError('ERROR_PASSTHROUGH_SEE_CAUSE_PROPERTY', 'NotAllowedError'),
        )

        await expect(passkeysApi.create({ nickname: 'Phone' })).rejects.toThrow(
            'Passkey setup was cancelled.',
        )

        expect(mockedPost).not.toHaveBeenCalled()
    })

    it('create names a device that already holds a passkey for the account', async () => {
        mockedGet.mockResolvedValue({ data: creationOptions })
        vi.mocked(startRegistration).mockRejectedValue(
            ceremonyError(
                'ERROR_AUTHENTICATOR_PREVIOUSLY_REGISTERED',
                'InvalidStateError',
            ),
        )

        await expect(passkeysApi.create({ nickname: 'Phone' })).rejects.toThrow(
            'This device already holds a passkey for your account.',
        )

        expect(mockedPost).not.toHaveBeenCalled()
    })
})

describe('passkey sign-in endpoints', () => {
    beforeEach(() => {
        vi.resetAllMocks()
    })

    it('loginOptions gets the sign-in options and returns them', async () => {
        mockedGet.mockResolvedValue({ data: requestOptions })

        await expect(loginOptions()).resolves.toBe(requestOptions)

        expect(mockedGet).toHaveBeenCalledExactlyOnceWith(
            '/v1/auth/passkeys/login/options',
        )
    })

    it('loginVerify posts the answer and resolves the whole response', async () => {
        const response = { data: plainUser } as AxiosResponse<AuthUser>
        mockedPost.mockResolvedValue(response)

        await expect(loginVerify(authenticationResponse)).resolves.toBe(response)

        expect(mockedPost).toHaveBeenCalledExactlyOnceWith(
            '/v1/auth/passkeys/login/verify',
            { credential: authenticationResponse },
        )
    })
})
