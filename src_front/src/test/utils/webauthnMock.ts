/** @file The partial mock of `@simplewebauthn/browser` that the passkey tests share. */

import { vi } from 'vitest'

/** The library's exports, as the real module provides them. */
type Browser = typeof import('@simplewebauthn/browser')

/**
 * Keep the library's errors and abort service, and replace what touches the browser.
 *
 * @param importOriginal - Vitest's loader for the real module.
 * @returns The module the tests see.
 */
export async function mockWebAuthnBrowser(
    importOriginal: () => Promise<Browser>,
): Promise<Browser> {
    return {
        ...(await importOriginal()),
        browserSupportsWebAuthn: vi.fn(),
        browserSupportsWebAuthnAutofill: vi.fn(),
        startAuthentication: vi.fn(),
        startRegistration: vi.fn(),
    }
}
