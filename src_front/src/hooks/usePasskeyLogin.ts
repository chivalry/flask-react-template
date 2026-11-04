/** @file The sign-in page's passkeys: its button, and the email field's autofill. */

import {
    browserSupportsWebAuthn,
    browserSupportsWebAuthnAutofill,
    startAuthentication,
    WebAuthnAbortService,
    type AuthenticationResponseJSON,
    type PublicKeyCredentialRequestOptionsJSON,
} from '@simplewebauthn/browser'
import type { AxiosResponse } from 'axios'
import { useEffect, useRef, useState, type RefObject } from 'react'

import { loginOptions, loginVerify } from '../api/passkeys'
import type { AuthUser } from '../types/auth'
import { isCancelledCeremony } from '../utils/passkeys'

/** A sign-in that resolves null when the visitor cancelled it. */
type SignInAction = () => Promise<AxiosResponse<AuthUser> | null>

/** The sign-in page's `handleAuthAction`, which shows a failure or navigates. */
export type RunAuthAction = (action: SignInAction, fallback: string) => Promise<void>

/** What an autofill offer shares with the hook and its button. */
interface PasskeyLoginRefs {
    /** The page's latest `handleAuthAction`. */
    runRef: RefObject<RunAuthAction>
    /** The running offer's controller, which the button aborts. */
    autofillRef: RefObject<AbortController | null>
    /** The button's sign-in's controller, which is null unless it runs. */
    buttonRef: RefObject<AbortController | null>
    /** The newest request that sets or clears the sign-in cookie. */
    pendingRequestRef: RefObject<Promise<unknown>>
}

/** What the page shows when a passkey sign-in fails without a message of its own. */
const FALLBACK_MESSAGE = 'Passkey sign-in failed.'

/** How often the autofill offer renews; the server keeps a challenge five minutes. */
const AUTOFILL_REFRESH_MS = 4 * 60 * 1000

/**
 * Send a request that sets or clears the sign-in cookie once every earlier one settles.
 *
 * Each sign-in options answer sets the cookie that holds its challenge, and each
 * verification's answer clears it, so whichever answer lands last decides the cookie.
 * Sending one request at a time makes that the newest request's answer. An earlier
 * request's failure holds nothing up, because its own caller handles it.
 *
 * @param pending - The newest such request, which this one replaces.
 * @param send - Sends the request.
 * @returns The request's answer.
 */
function sendAfterEarlierRequests<T>(
    pending: RefObject<Promise<unknown>>,
    send: () => Promise<T>,
): Promise<T> {
    const request = pending.current.then(
        () => send(),
        () => send(),
    )
    pending.current = request
    return request
}

/**
 * Sign in through the browser's own passkey prompt.
 *
 * The options and the verification each wait for the requests before them. An unmount
 * stops the sign-in between its steps: once the options load, so that no prompt opens
 * on a page that is gone, and again once the prompt answers, so that nothing is
 * verified.
 *
 * @param signal - Aborted when the page unmounts.
 * @param pending - The newest request that sets or clears the sign-in cookie.
 * @returns The response with the signed-in user, or null when the visitor dismissed the
 *   prompt, a newer ceremony replaced it, or the page unmounted.
 */
async function signInThroughPrompt(
    signal: AbortSignal,
    pending: RefObject<Promise<unknown>>,
): Promise<AxiosResponse<AuthUser> | null> {
    const optionsJSON = await sendAfterEarlierRequests(pending, loginOptions)
    if (signal.aborted) return null
    let credential: AuthenticationResponseJSON
    try {
        credential = await startAuthentication({ optionsJSON })
    } catch (err: unknown) {
        if (isCancelledCeremony(err)) return null
        throw err
    }
    if (signal.aborted) return null
    return sendAfterEarlierRequests(pending, () => loginVerify(credential))
}

/**
 * Offer the site's passkeys in the email field's autofill, where the browser can.
 *
 * The page's `handleAuthAction` runs only once the visitor picks a passkey, because it
 * clears the page's error first, and an offer that renews must not erase the message of
 * a sign-in that just failed. Options that fail to load, and a ceremony that ends without
 * a pick, leave the page as it was. The options, and a picked passkey's verification,
 * each wait for the requests before them. An offer that has ended verifies nothing:
 * the browser keeps its suggestions until the button's prompt replaces them, and a
 * passkey picked meanwhile answers a challenge that the button's options replaced.
 *
 * @param signal - Aborted when a newer offer, the button, or an unmount ends this one.
 * @param pending - The newest request that sets or clears the sign-in cookie.
 * @param run - Runs the sign-in as `handleAuthAction` does.
 * @returns Whether the visitor picked a passkey, once its sign-in settles.
 */
async function offerAutofill(
    signal: AbortSignal,
    pending: RefObject<Promise<unknown>>,
    run: (action: SignInAction) => Promise<void>,
): Promise<boolean> {
    if (!(await browserSupportsWebAuthnAutofill()) || signal.aborted) return false
    let optionsJSON: PublicKeyCredentialRequestOptionsJSON
    try {
        optionsJSON = await sendAfterEarlierRequests(pending, loginOptions)
    } catch {
        return false
    }
    if (signal.aborted) return false
    let credential: AuthenticationResponseJSON
    try {
        credential = await startAuthentication({ optionsJSON, useBrowserAutofill: true })
    } catch {
        return false
    }
    if (signal.aborted) return false
    await run(() => sendAfterEarlierRequests(pending, () => loginVerify(credential)))
    return true
}

/**
 * Start an autofill offer, unless the button's sign-in is running.
 *
 * The offer signs a picked passkey in through the page's latest `handleAuthAction`. It
 * renews once its four minutes are up, and at once after a passkey picked from it fails.
 * Its cleanup ends it, and cancels its ceremony unless the button's prompt has taken
 * that ceremony's place.
 *
 * @param refs - What the offer shares with the hook and its button.
 * @param renew - Starts the next offer.
 * @returns The cleanup, or undefined when the button's sign-in is running.
 */
function startAutofillOffer(
    refs: PasskeyLoginRefs,
    renew: () => void,
): (() => void) | undefined {
    if (refs.buttonRef.current) return undefined
    const controller = new AbortController()
    refs.autofillRef.current = controller
    void offerAutofill(controller.signal, refs.pendingRequestRef, (action) =>
        refs.runRef.current(action, FALLBACK_MESSAGE),
    ).then((picked) => {
        // A pick ends the browser's request, so after a failed one the offer renews.
        if (picked && !controller.signal.aborted) renew()
    })
    const timer = setTimeout(renew, AUTOFILL_REFRESH_MS)
    return () => {
        clearTimeout(timer)
        controller.abort()
        if (!refs.buttonRef.current) WebAuthnAbortService.cancelCeremony()
    }
}

/**
 * Offer passkey sign-in on the sign-in page.
 *
 * The autofill offer starts when the page mounts. A browser's autofill request never
 * times out, but the server's challenge does, so the offer renews every four minutes,
 * at once after a passkey picked from it fails, and again once the button's sign-in
 * settles. The button ends the offer first, even one whose options are still loading,
 * because starting a ceremony aborts the one before it; no offer starts while the
 * button's prompt is open. Each options request and each verification, the button's
 * and the autofill's alike, waits until the one before it settles: an options answer
 * sets the cookie that holds its challenge, a verification's answer clears it, and the
 * answer that lands last decides it, which must be the newest request's. Unmounting
 * cancels whichever ceremony runs and stops the button's sign-in between its steps.
 * The effects read `run` through a ref, because the page's `handleAuthAction` changes
 * on every render; `eslint-plugin-react-hooks` 5 predates `useEffectEvent`.
 *
 * @param run - The page's `handleAuthAction`.
 * @returns `available`, whether this browser can use passkeys; `pending`, whether the
 *   button's sign-in is running; and `signIn`, which runs it.
 */
export function usePasskeyLogin(run: RunAuthAction) {
    const runRef = useRef(run)
    const autofillRef = useRef<AbortController | null>(null)
    const buttonRef = useRef<AbortController | null>(null)
    const pendingRequestRef = useRef<Promise<unknown>>(Promise.resolve())
    const [offer, setOffer] = useState(0)
    const [available] = useState(browserSupportsWebAuthn)
    const [pending, setPending] = useState(false)

    useEffect(() => {
        runRef.current = run
    })

    useEffect(
        () => () => {
            buttonRef.current?.abort()
            WebAuthnAbortService.cancelCeremony()
        },
        [],
    )

    useEffect(() => {
        const refs = { runRef, autofillRef, buttonRef, pendingRequestRef }
        return startAutofillOffer(refs, () => setOffer(offer + 1))
    }, [offer])

    /** Sign in through the browser's prompt, which replaces the autofill offer. */
    const signIn = async () => {
        const controller = new AbortController()
        buttonRef.current = controller
        autofillRef.current?.abort()
        setPending(true)
        try {
            await run(
                () => signInThroughPrompt(controller.signal, pendingRequestRef),
                FALLBACK_MESSAGE,
            )
        } finally {
            buttonRef.current = null
            setPending(false)
            setOffer((count) => count + 1)
        }
    }

    return { available, pending, signIn }
}
