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
import { useEffect, useRef, useState } from 'react'

import { loginOptions, loginVerify } from '../api/passkeys'
import type { AuthUser } from '../types/auth'
import { isCancelledCeremony } from '../utils/passkeys'

/** A sign-in that resolves null when the visitor cancelled it. */
type SignInAction = () => Promise<AxiosResponse<AuthUser> | null>

/** The sign-in page's `handleAuthAction`, which shows a failure or navigates. */
export type RunAuthAction = (action: SignInAction, fallback: string) => Promise<void>

/** What the page shows when a passkey sign-in fails without a message of its own. */
const FALLBACK_MESSAGE = 'Passkey sign-in failed.'

/** How often the autofill offer renews; the server keeps a challenge five minutes. */
const AUTOFILL_REFRESH_MS = 4 * 60 * 1000

/**
 * Sign in through the browser's own passkey prompt.
 *
 * @returns The response with the signed-in user, or null when the visitor dismissed the
 *   prompt or a newer ceremony replaced it.
 */
async function signInThroughPrompt(): Promise<AxiosResponse<AuthUser> | null> {
    const optionsJSON = await loginOptions()
    let credential: AuthenticationResponseJSON
    try {
        credential = await startAuthentication({ optionsJSON })
    } catch (err: unknown) {
        if (isCancelledCeremony(err)) return null
        throw err
    }
    return loginVerify(credential)
}

/**
 * Offer the site's passkeys in the email field's autofill, where the browser can.
 *
 * The page's `handleAuthAction` runs only once the visitor picks a passkey, because it
 * clears the page's error first, and an offer that renews must not erase the message of
 * a sign-in that just failed. Options that fail to load, and a ceremony that ends without
 * a pick, leave the page as it was.
 *
 * @param signal - Aborted when a newer offer, the button, or an unmount ends this one.
 * @param run - Runs the sign-in as `handleAuthAction` does.
 * @returns Whether the visitor picked a passkey, once its sign-in settles.
 */
async function offerAutofill(
    signal: AbortSignal,
    run: (action: SignInAction) => Promise<void>,
): Promise<boolean> {
    if (!(await browserSupportsWebAuthnAutofill()) || signal.aborted) return false
    let optionsJSON: PublicKeyCredentialRequestOptionsJSON
    try {
        optionsJSON = await loginOptions()
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
    await run(() => loginVerify(credential))
    return true
}

/**
 * Offer passkey sign-in on the sign-in page.
 *
 * The autofill offer starts when the page mounts. A browser's autofill request never
 * times out, but the server's challenge does, so the offer renews every four minutes,
 * at once after a passkey picked from it fails, and again once the button's sign-in
 * settles. The button ends the offer first, even one whose options are still loading,
 * because starting a ceremony aborts the one before it; no offer starts while the
 * button's prompt is open, and unmounting cancels whichever ceremony runs. The effects
 * read `run` through a ref, because the page's `handleAuthAction` changes on every
 * render; `eslint-plugin-react-hooks` 5 predates `useEffectEvent`.
 *
 * @param run - The page's `handleAuthAction`.
 * @returns `available`, whether this browser can use passkeys; `pending`, whether the
 *   button's sign-in is running; and `signIn`, which runs it.
 */
export function usePasskeyLogin(run: RunAuthAction) {
    const runRef = useRef(run)
    const autofillRef = useRef<AbortController | null>(null)
    const buttonBusyRef = useRef(false)
    const [offer, setOffer] = useState(0)
    const [available] = useState(browserSupportsWebAuthn)
    const [pending, setPending] = useState(false)

    useEffect(() => {
        runRef.current = run
    })

    useEffect(() => () => WebAuthnAbortService.cancelCeremony(), [])

    useEffect(() => {
        if (buttonBusyRef.current) return
        const controller = new AbortController()
        autofillRef.current = controller
        void offerAutofill(controller.signal, (action) =>
            runRef.current(action, FALLBACK_MESSAGE),
        ).then((picked) => {
            // A pick ends the browser's request, so after a failed one the offer renews.
            if (picked && !controller.signal.aborted) setOffer(offer + 1)
        })
        const timer = setTimeout(() => setOffer(offer + 1), AUTOFILL_REFRESH_MS)
        return () => {
            clearTimeout(timer)
            controller.abort()
            if (!buttonBusyRef.current) WebAuthnAbortService.cancelCeremony()
        }
    }, [offer])

    /** Sign in through the browser's prompt, which replaces the autofill offer. */
    const signIn = async () => {
        buttonBusyRef.current = true
        autofillRef.current?.abort()
        setPending(true)
        try {
            await run(signInThroughPrompt, FALLBACK_MESSAGE)
        } finally {
            buttonBusyRef.current = false
            setPending(false)
            setOffer((count) => count + 1)
        }
    }

    return { available, pending, signIn }
}
