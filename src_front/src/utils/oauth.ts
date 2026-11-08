/** @file The link that starts a provider sign-in, and the messages for its failures. */

/** A `Map`, so a crafted `?error=__proto__` finds no inherited property to render. */
const ERROR_MESSAGES = new Map([
    ['unknown_provider', 'That sign-in provider is not available.'],
    ['cancelled', 'Sign-in was cancelled.'],
    ['invalid_state', 'That sign-in could not be verified. Please try again.'],
    ['expired', 'That sign-in took too long. Please try again.'],
    ['exchange_failed', 'The sign-in provider could not finish. Please try again.'],
    ['invalid_token', 'The sign-in could not be verified. Please try again.'],
    [
        'email_required',
        'The sign-in provider did not share an email address, which every account here ' +
            'needs. Share it and try again, or sign in another way.',
    ],
    ['email_unverified', 'Verify your email with the sign-in provider, then try again.'],
    [
        'link_required',
        'That email already has an account. Sign in, then link it from Account.',
    ],
    ['already_linked', 'That account is already linked to a sign-in provider.'],
    ['account_inactive', 'Account is inactive.'],
])

/** What to show for a code this build does not know. */
const FALLBACK_MESSAGE = 'Sign-in failed. Please try again.'

/**
 * Build the link that starts a sign-in.
 *
 * It is a plain URL rather than an API call: the browser leaves the page for the
 * provider, so it includes the `/api` prefix the axios client would add.
 *
 * @param name - The provider's name.
 * @param next - The path to return to.
 * @returns The URL to navigate to.
 */
export function startUrl(name: string, next?: string): string {
    const query = next ? `?next=${encodeURIComponent(next)}` : ''
    return `/api/v1/auth/oauth/${encodeURIComponent(name)}/start${query}`
}

/**
 * Build the link that attaches a provider to the signed-in account.
 *
 * A session alone is not enough for the server to link, so this link asks for it.
 *
 * @param name - The provider's name.
 * @returns The URL to navigate to.
 */
export function linkUrl(name: string): string {
    return `${startUrl(name, '/account')}&link=1`
}

/**
 * Turn the `error` query parameter a failed provider sign-in redirects with into text.
 *
 * The code itself is never shown, since anyone can write it into a link.
 *
 * @param code - The parameter's value, or null when it is absent.
 * @returns The message to show, or null when there is no code.
 */
export function oauthErrorMessage(code: string | null): string | null {
    if (!code) return null
    return ERROR_MESSAGES.get(code) ?? FALLBACK_MESSAGE
}
