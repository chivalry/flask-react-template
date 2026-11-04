/** @file The sign-in page's passkey button, and the autofill offer it keeps fresh. */

import {
    browserSupportsWebAuthn,
    browserSupportsWebAuthnAutofill,
    startAuthentication,
    WebAuthnAbortService,
    type AuthenticationResponseJSON,
    type PublicKeyCredentialRequestOptionsJSON,
} from '@simplewebauthn/browser'
import { act, cleanup, renderHook, waitFor } from '@testing-library/react'
import type { AxiosResponse } from 'axios'
import {
    afterEach,
    beforeEach,
    describe,
    expect,
    it,
    vi,
    type MockInstance,
} from 'vitest'

import { loginOptions, loginVerify } from '../../api/passkeys'
import { usePasskeyLogin, type RunAuthAction } from '../../hooks/usePasskeyLogin'
import type { AuthUser } from '../../types/auth'
import { plainUser } from '../utils/fixtures'
import { authenticationResponse, ceremonyError, requestOptions } from '../utils/webauthn'

vi.mock('@simplewebauthn/browser', async (importOriginal) =>
    (await import('../utils/webauthnMock')).mockWebAuthnBrowser(importOriginal),
)
vi.mock('../../api/passkeys')

/** What the page shows when a passkey sign-in fails without a message of its own. */
const FALLBACK = 'Passkey sign-in failed.'

/** How often the autofill offer renews. */
const FOUR_MINUTES = 4 * 60 * 1000

/** The answer of a passkey that verified. */
const verified = { data: plainUser } as AxiosResponse<AuthUser>

/** How one sign-in the page ran settled: what it resolved, or what it threw. */
interface Settled {
    resolved?: AxiosResponse<AuthUser> | null
    thrown?: unknown
}

/** A promise with its settling handed out, for a step the test finishes itself. */
function deferred<T>() {
    let resolve: (value: T) => void = () => undefined
    let reject: (reason: unknown) => void = () => undefined
    const promise = new Promise<T>((settleWith, failWith) => {
        resolve = settleWith
        reject = failWith
    })
    return { promise, resolve, reject }
}

/** Sign-in options that load, or fail to, only when the test says. */
type HeldOptions = ReturnType<typeof deferred<PublicKeyCredentialRequestOptionsJSON>>

/** A prompt the visitor never answers. */
const unanswered = <T,>() => new Promise<T>(() => undefined)

/**
 * Stand in for the page's `handleAuthAction`: await the action and record how it
 * settled.
 *
 * @returns The double, and what each sign-in it ran settled with.
 */
function recordingRun() {
    const settled: Settled[] = []
    const run = vi.fn<RunAuthAction>(async (action) => {
        try {
            settled.push({ resolved: await action() })
        } catch (err: unknown) {
            settled.push({ thrown: err })
        }
    })
    return { run, settled }
}

/** Render the hook with a `run` that a rerender can replace. */
const renderPasskeyLogin = (run: RunAuthAction) =>
    renderHook((props: { run: RunAuthAction }) => usePasskeyLogin(props.run), {
        initialProps: { run },
    })

/** Let every pending promise, and the React updates they make, run. */
const settle = () => act(() => new Promise<void>((resolve) => setTimeout(resolve, 0)))

/** Start the button's sign-in without waiting for it to settle. */
const clickPasskeyButton = (signIn: () => Promise<void>) =>
    act(() => {
        void signIn()
    })

/** Leave every autofill prompt unanswered, and answer the button's with `answer`. */
function answerOnlyTheButton(answer: Promise<AuthenticationResponseJSON>) {
    vi.mocked(startAuthentication).mockImplementation(({ useBrowserAutofill }) =>
        useBrowserAutofill ? unanswered() : answer,
    )
}

/** The options of every call to `startAuthentication`, in order. */
const ceremonies = () => vi.mocked(startAuthentication).mock.calls.map(([opts]) => opts)

describe('usePasskeyLogin', () => {
    let cancelCeremony: MockInstance<() => void>

    beforeEach(() => {
        vi.resetAllMocks()
        cancelCeremony = vi.spyOn(WebAuthnAbortService, 'cancelCeremony')
        vi.mocked(browserSupportsWebAuthn).mockReturnValue(true)
        vi.mocked(browserSupportsWebAuthnAutofill).mockResolvedValue(false)
        vi.mocked(loginOptions).mockResolvedValue(requestOptions)
        vi.mocked(loginVerify).mockResolvedValue(verified)
        vi.mocked(startAuthentication).mockReturnValue(unanswered())
    })

    afterEach(() => {
        vi.restoreAllMocks()
    })

    it.each([true, false])(
        'reports available as %s, as the browser does',
        (supported) => {
            vi.mocked(browserSupportsWebAuthn).mockReturnValue(supported)

            const { result } = renderPasskeyLogin(recordingRun().run)

            expect(result.current.available).toBe(supported)
        },
    )

    it('offers passkeys in the autofill and signs in with the one picked', async () => {
        vi.mocked(browserSupportsWebAuthnAutofill).mockResolvedValue(true)
        vi.mocked(startAuthentication).mockResolvedValueOnce(authenticationResponse)
        const { run, settled } = recordingRun()

        renderPasskeyLogin(run)

        await waitFor(() => expect(settled).toEqual([{ resolved: verified }]))
        expect(loginOptions).toHaveBeenCalled()
        expect(ceremonies()[0]).toEqual({
            optionsJSON: requestOptions,
            useBrowserAutofill: true,
        })
        expect(loginVerify).toHaveBeenCalledExactlyOnceWith(authenticationResponse)
        expect(run).toHaveBeenCalledExactlyOnceWith(expect.any(Function), FALLBACK)
        // The pick ended the browser's request, so a new offer takes its place.
        await waitFor(() => expect(startAuthentication).toHaveBeenCalledTimes(2))
    })

    it('loads no options where the browser has no autofill', async () => {
        renderPasskeyLogin(recordingRun().run)

        await waitFor(() => expect(browserSupportsWebAuthnAutofill).toHaveBeenCalled())
        await settle()

        expect(loginOptions).not.toHaveBeenCalled()
    })

    it('runs nothing when the options fail to load', async () => {
        vi.mocked(browserSupportsWebAuthnAutofill).mockResolvedValue(true)
        vi.mocked(loginOptions).mockRejectedValue(new Error('Network Error'))
        const { run } = recordingRun()

        renderPasskeyLogin(run)

        await waitFor(() => expect(loginOptions).toHaveBeenCalledTimes(1))
        await settle()
        expect(startAuthentication).not.toHaveBeenCalled()
        expect(run).not.toHaveBeenCalled()
    })

    it.each([
        ['an abort', ceremonyError('ERROR_CEREMONY_ABORTED', 'AbortError')],
        ['another failure', new Error('No input asks for webauthn autofill.')],
    ])(
        'ends the offer on %s without a sign-in or a new offer',
        async (_label, failure) => {
            vi.mocked(browserSupportsWebAuthnAutofill).mockResolvedValue(true)
            vi.mocked(startAuthentication).mockRejectedValue(failure)
            const { run } = recordingRun()

            renderPasskeyLogin(run)

            await waitFor(() => expect(startAuthentication).toHaveBeenCalledTimes(1))
            await settle()
            await settle()
            expect(run).not.toHaveBeenCalled()
            expect(loginVerify).not.toHaveBeenCalled()
            expect(loginOptions).toHaveBeenCalledTimes(1)
        },
    )

    it('renews the offer at once after a picked passkey fails to sign in', async () => {
        const refused = new Error('That passkey was not accepted.')
        vi.mocked(browserSupportsWebAuthnAutofill).mockResolvedValue(true)
        vi.mocked(startAuthentication).mockResolvedValueOnce(authenticationResponse)
        vi.mocked(loginVerify).mockRejectedValue(refused)
        const { run, settled } = recordingRun()

        renderPasskeyLogin(run)

        await waitFor(() => expect(loginOptions).toHaveBeenCalledTimes(2))
        await waitFor(() => expect(startAuthentication).toHaveBeenCalledTimes(2))
        expect(settled).toEqual([{ thrown: refused }])
    })

    it('renews only once a picked passkey has finished signing in', async () => {
        vi.mocked(browserSupportsWebAuthnAutofill).mockResolvedValue(true)
        vi.mocked(startAuthentication).mockResolvedValueOnce(authenticationResponse)
        const answer = deferred<AxiosResponse<AuthUser>>()
        vi.mocked(loginVerify).mockReturnValue(answer.promise)
        const { run } = recordingRun()

        renderPasskeyLogin(run)
        await waitFor(() => expect(loginVerify).toHaveBeenCalledTimes(1))
        await settle()

        // Options asked for now could be answered before the sign-in is, and the
        // sign-in's answer clears the cookie that holds their challenge.
        expect(loginOptions).toHaveBeenCalledTimes(1)
        await act(async () => answer.resolve(verified))
        await waitFor(() => expect(loginOptions).toHaveBeenCalledTimes(2))
    })

    it('keeps the failed button sign-in error through the renewed offer', async () => {
        vi.mocked(browserSupportsWebAuthnAutofill).mockResolvedValue(true)
        answerOnlyTheButton(Promise.resolve(authenticationResponse))
        vi.mocked(loginVerify).mockRejectedValue(
            new Error('That passkey was not accepted.'),
        )
        const { run, settled } = recordingRun()
        const { result } = renderPasskeyLogin(run)
        await waitFor(() => expect(startAuthentication).toHaveBeenCalledTimes(1))

        await act(() => result.current.signIn())

        await waitFor(() => expect(startAuthentication).toHaveBeenCalledTimes(3))
        expect(ceremonies()[2]).toEqual({
            optionsJSON: requestOptions,
            useBrowserAutofill: true,
        })
        // handleAuthAction clears the page's error, so only a pick may call it.
        expect(run).toHaveBeenCalledTimes(1)
        expect(settled).toHaveLength(1)
    })

    it('cancels the ceremony on unmount', () => {
        const { unmount } = renderPasskeyLogin(recordingRun().run)

        unmount()

        expect(cancelCeremony).toHaveBeenCalled()
    })

    it('cancels the button prompt on unmount too', async () => {
        const { result, unmount } = renderPasskeyLogin(recordingRun().run)
        clickPasskeyButton(result.current.signIn)
        await waitFor(() => expect(startAuthentication).toHaveBeenCalledTimes(1))
        cancelCeremony.mockClear()

        unmount()

        expect(cancelCeremony).toHaveBeenCalledTimes(1)
    })

    it('loads no options when unmounted during the support check', async () => {
        const support = deferred<boolean>()
        vi.mocked(browserSupportsWebAuthnAutofill).mockReturnValue(support.promise)
        const { unmount } = renderPasskeyLogin(recordingRun().run)
        await waitFor(() => expect(browserSupportsWebAuthnAutofill).toHaveBeenCalled())

        unmount()
        support.resolve(true)
        await settle()

        expect(loginOptions).not.toHaveBeenCalled()
    })

    it('starts no ceremony when unmounted while the options load', async () => {
        const options = deferred<PublicKeyCredentialRequestOptionsJSON>()
        vi.mocked(browserSupportsWebAuthnAutofill).mockResolvedValue(true)
        vi.mocked(loginOptions).mockReturnValue(options.promise)
        const { unmount } = renderPasskeyLogin(recordingRun().run)
        await waitFor(() => expect(loginOptions).toHaveBeenCalledTimes(1))

        unmount()
        options.resolve(requestOptions)
        await settle()

        expect(startAuthentication).not.toHaveBeenCalled()
    })

    it('opens no prompt when unmounted while the button options load', async () => {
        const options = deferred<PublicKeyCredentialRequestOptionsJSON>()
        vi.mocked(loginOptions).mockReturnValue(options.promise)
        const { run, settled } = recordingRun()
        const { result, unmount } = renderPasskeyLogin(run)
        clickPasskeyButton(result.current.signIn)
        await waitFor(() => expect(loginOptions).toHaveBeenCalledTimes(1))

        unmount()
        options.resolve(requestOptions)
        await settle()

        expect(startAuthentication).not.toHaveBeenCalled()
        expect(settled).toEqual([{ resolved: null }])
    })

    it('verifies nothing when unmounted after the button prompt answers', async () => {
        const prompt = deferred<AuthenticationResponseJSON>()
        vi.mocked(startAuthentication).mockReturnValue(prompt.promise)
        const { run, settled } = recordingRun()
        const { result, unmount } = renderPasskeyLogin(run)
        clickPasskeyButton(result.current.signIn)
        await waitFor(() => expect(startAuthentication).toHaveBeenCalledTimes(1))

        prompt.resolve(authenticationResponse)
        unmount()
        await settle()

        expect(loginVerify).not.toHaveBeenCalled()
        expect(settled).toEqual([{ resolved: null }])
    })

    it('signs in through the prompt, pending until it settles', async () => {
        const prompt = deferred<AuthenticationResponseJSON>()
        vi.mocked(startAuthentication).mockReturnValue(prompt.promise)
        const { run, settled } = recordingRun()
        const { result } = renderPasskeyLogin(run)
        expect(result.current.pending).toBe(false)

        let signingIn = Promise.resolve()
        act(() => {
            signingIn = result.current.signIn()
        })

        expect(result.current.pending).toBe(true)
        await waitFor(() => expect(startAuthentication).toHaveBeenCalledTimes(1))
        expect(ceremonies()).toStrictEqual([{ optionsJSON: requestOptions }])
        expect(result.current.pending).toBe(true)
        await act(async () => {
            prompt.resolve(authenticationResponse)
            await signingIn
        })
        expect(result.current.pending).toBe(false)
        expect(loginOptions).toHaveBeenCalledTimes(1)
        expect(loginVerify).toHaveBeenCalledExactlyOnceWith(authenticationResponse)
        expect(settled).toEqual([{ resolved: verified }])
        expect(run).toHaveBeenCalledExactlyOnceWith(expect.any(Function), FALLBACK)
    })

    it('resolves a dismissed prompt to null', async () => {
        vi.mocked(startAuthentication).mockRejectedValue(
            ceremonyError('ERROR_PASSTHROUGH_SEE_CAUSE_PROPERTY', 'NotAllowedError'),
        )
        const { run, settled } = recordingRun()
        const { result } = renderPasskeyLogin(run)

        await act(() => result.current.signIn())

        expect(settled).toEqual([{ resolved: null }])
        expect(loginVerify).not.toHaveBeenCalled()
    })

    it('rejects with any other ceremony error', async () => {
        const failure = ceremonyError('ERROR_INVALID_DOMAIN', 'SecurityError')
        vi.mocked(startAuthentication).mockRejectedValue(failure)
        const { run, settled } = recordingRun()
        const { result } = renderPasskeyLogin(run)

        await act(() => result.current.signIn())

        expect(settled).toHaveLength(1)
        expect(settled[0].thrown).toBe(failure)
        expect(loginVerify).not.toHaveBeenCalled()
    })

    it('signs a pick in through the latest run, loading the options once', async () => {
        const options = deferred<PublicKeyCredentialRequestOptionsJSON>()
        vi.mocked(browserSupportsWebAuthnAutofill).mockResolvedValue(true)
        vi.mocked(loginOptions).mockReturnValueOnce(options.promise)
        vi.mocked(startAuthentication).mockResolvedValueOnce(authenticationResponse)
        const first = recordingRun()
        const latest = recordingRun()
        const { rerender } = renderPasskeyLogin(first.run)
        await waitFor(() => expect(loginOptions).toHaveBeenCalledTimes(1))

        rerender({ run: latest.run })
        await settle()
        expect(loginOptions).toHaveBeenCalledTimes(1)

        options.resolve(requestOptions)
        await waitFor(() => expect(latest.settled).toEqual([{ resolved: verified }]))
        expect(first.run).not.toHaveBeenCalled()
        await waitFor(() => expect(startAuthentication).toHaveBeenCalledTimes(2))
    })

    it.each([
        ['load', (options: HeldOptions) => options.resolve(requestOptions)],
        ['fail', (options: HeldOptions) => options.reject(new Error('Network Error'))],
    ])(
        'asks for the button options only once the autofill options %s',
        async (_label, finishAutofillOptions) => {
            const autofillOptions = deferred<PublicKeyCredentialRequestOptionsJSON>()
            vi.mocked(browserSupportsWebAuthnAutofill).mockResolvedValue(true)
            vi.mocked(loginOptions).mockReturnValueOnce(autofillOptions.promise)
            const { result } = renderPasskeyLogin(recordingRun().run)
            await waitFor(() => expect(loginOptions).toHaveBeenCalledTimes(1))

            clickPasskeyButton(result.current.signIn)
            await settle()
            expect(loginOptions).toHaveBeenCalledTimes(1)

            finishAutofillOptions(autofillOptions)
            await waitFor(() => expect(startAuthentication).toHaveBeenCalledTimes(1))
            await settle()

            expect(loginOptions).toHaveBeenCalledTimes(2)
            // A late autofill ceremony would abort the button's prompt.
            expect(ceremonies()).toStrictEqual([{ optionsJSON: requestOptions }])
        },
    )

    it('verifies nothing for a passkey picked once a click ended the offer', async () => {
        const autofillAnswer = deferred<AuthenticationResponseJSON>()
        const buttonOptions = deferred<PublicKeyCredentialRequestOptionsJSON>()
        vi.mocked(browserSupportsWebAuthnAutofill).mockResolvedValue(true)
        vi.mocked(startAuthentication)
            .mockReturnValueOnce(autofillAnswer.promise)
            .mockResolvedValueOnce(authenticationResponse)
        const { run, settled } = recordingRun()
        const { result } = renderPasskeyLogin(run)
        await waitFor(() => expect(startAuthentication).toHaveBeenCalledTimes(1))

        vi.mocked(loginOptions).mockReturnValueOnce(buttonOptions.promise)
        clickPasskeyButton(result.current.signIn)
        // The browser keeps its suggestions until the button's prompt replaces them.
        autofillAnswer.resolve(authenticationResponse)
        await settle()
        expect(run).toHaveBeenCalledTimes(1)

        buttonOptions.resolve(requestOptions)
        await waitFor(() => expect(settled).toEqual([{ resolved: verified }]))
        await settle()
        expect(run).toHaveBeenCalledTimes(1)
        expect(loginVerify).toHaveBeenCalledTimes(1)
    })

    describe('on a fake clock', () => {
        /** Move the clock on, letting promises and React updates run as it goes. */
        const advance = (ms: number) => act(() => vi.advanceTimersByTimeAsync(ms))

        /** Let every pending promise, and the React updates they make, run. */
        const flush = () => advance(0)

        beforeEach(() => {
            vi.useFakeTimers()
            vi.mocked(browserSupportsWebAuthnAutofill).mockResolvedValue(true)
        })

        afterEach(() => {
            cleanup()
            vi.useRealTimers()
        })

        it('renews the autofill offer every four minutes', async () => {
            renderPasskeyLogin(recordingRun().run)
            await flush()
            expect(loginOptions).toHaveBeenCalledTimes(1)
            expect(startAuthentication).toHaveBeenCalledTimes(1)

            await advance(FOUR_MINUTES - 1)
            await flush()
            expect(loginOptions).toHaveBeenCalledTimes(1)

            await advance(1)
            await flush()
            expect(loginOptions).toHaveBeenCalledTimes(2)
            expect(ceremonies()).toEqual([
                { optionsJSON: requestOptions, useBrowserAutofill: true },
                { optionsJSON: requestOptions, useBrowserAutofill: true },
            ])
        })

        it('starts no offer and cancels nothing while the prompt is open', async () => {
            const { result } = renderPasskeyLogin(recordingRun().run)
            await flush()
            clickPasskeyButton(result.current.signIn)
            await flush()
            expect(loginOptions).toHaveBeenCalledTimes(2)
            expect(startAuthentication).toHaveBeenCalledTimes(2)
            cancelCeremony.mockClear()

            await advance(FOUR_MINUTES)
            await flush()

            expect(loginOptions).toHaveBeenCalledTimes(2)
            expect(startAuthentication).toHaveBeenCalledTimes(2)
            expect(cancelCeremony).not.toHaveBeenCalled()
            expect(result.current.pending).toBe(true)
        })

        it('starts the offer again once a dismissed button prompt settles', async () => {
            const prompt = deferred<AuthenticationResponseJSON>()
            answerOnlyTheButton(prompt.promise)
            const { result } = renderPasskeyLogin(recordingRun().run)
            await flush()
            clickPasskeyButton(result.current.signIn)
            await flush()
            expect(loginOptions).toHaveBeenCalledTimes(2)

            prompt.reject(
                ceremonyError('ERROR_PASSTHROUGH_SEE_CAUSE_PROPERTY', 'NotAllowedError'),
            )
            await flush()
            await flush()

            expect(result.current.pending).toBe(false)
            expect(loginOptions).toHaveBeenCalledTimes(3)
            expect(ceremonies()).toEqual([
                { optionsJSON: requestOptions, useBrowserAutofill: true },
                { optionsJSON: requestOptions },
                { optionsJSON: requestOptions, useBrowserAutofill: true },
            ])
        })

        it.each([
            ['a click', clickPasskeyButton, { optionsJSON: requestOptions }],
            [
                'the four-minute renewal',
                () => advance(FOUR_MINUTES),
                { optionsJSON: requestOptions, useBrowserAutofill: true },
            ],
        ])(
            'asks for no options on %s until a picked passkey has verified',
            async (_label, trigger, nextCeremony) => {
                const answer = deferred<AxiosResponse<AuthUser>>()
                vi.mocked(startAuthentication).mockResolvedValueOnce(
                    authenticationResponse,
                )
                vi.mocked(loginVerify).mockReturnValue(answer.promise)
                const { result } = renderPasskeyLogin(recordingRun().run)
                await flush()
                expect(loginVerify).toHaveBeenCalledTimes(1)

                await trigger(result.current.signIn)
                await flush()
                expect(loginOptions).toHaveBeenCalledTimes(1)

                await act(async () => answer.resolve(verified))
                await flush()
                expect(loginOptions).toHaveBeenCalledTimes(2)
                expect(ceremonies()).toEqual([
                    { optionsJSON: requestOptions, useBrowserAutofill: true },
                    nextCeremony,
                ])
            },
        )
    })
})
