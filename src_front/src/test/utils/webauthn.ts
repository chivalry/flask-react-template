/** @file WebAuthn stand-ins for the tests: options, answers, and a prompt's errors. */

import {
    WebAuthnError,
    type AuthenticationResponseJSON,
    type PublicKeyCredentialCreationOptionsJSON,
    type PublicKeyCredentialRequestOptionsJSON,
    type RegistrationResponseJSON,
} from '@simplewebauthn/browser'

/** Sign-in options as the server sends them. */
export const requestOptions: PublicKeyCredentialRequestOptionsJSON = {
    challenge: 'c2lnbi1pbi1jaGFsbGVuZ2U',
    rpId: 'localhost',
    allowCredentials: [],
    userVerification: 'required',
    timeout: 300000,
}

/** Registration options as the server sends them. */
export const creationOptions: PublicKeyCredentialCreationOptionsJSON = {
    challenge: 'cmVnaXN0ZXItY2hhbGxlbmdl',
    rp: { id: 'localhost', name: 'Flask React Template' },
    user: {
        id: 'dXNlci11dWlkLTI',
        name: 'user@example.com',
        displayName: 'user@example.com',
    },
    pubKeyCredParams: [{ type: 'public-key', alg: -7 }],
    excludeCredentials: [],
    authenticatorSelection: { residentKey: 'required', userVerification: 'required' },
    attestation: 'none',
    timeout: 300000,
}

/** The browser's answer to the sign-in options. */
export const authenticationResponse: AuthenticationResponseJSON = {
    id: 'Y3JlZGVudGlhbC1pZA',
    rawId: 'Y3JlZGVudGlhbC1pZA',
    type: 'public-key',
    response: {
        clientDataJSON: 'e30',
        authenticatorData: 'AAAA',
        signature: 'AAAA',
        userHandle: 'dXNlci11dWlkLTI',
    },
    clientExtensionResults: {},
}

/** The browser's answer to the registration options. */
export const registrationResponse: RegistrationResponseJSON = {
    id: 'Y3JlZGVudGlhbC1pZA',
    rawId: 'Y3JlZGVudGlhbC1pZA',
    type: 'public-key',
    response: {
        clientDataJSON: 'e30',
        attestationObject: 'AAAA',
        transports: ['internal'],
    },
    clientExtensionResults: {},
}

/**
 * Build the error a passkey prompt rejects with.
 *
 * @param code - The library's code for it.
 * @param name - The browser's name for it, such as `NotAllowedError`.
 * @returns The error, as `@simplewebauthn/browser` throws it.
 */
export function ceremonyError(code: WebAuthnError['code'], name: string): WebAuthnError {
    const cause = new Error('The browser refused.')
    cause.name = name
    return new WebAuthnError({ message: cause.message, code, cause })
}
