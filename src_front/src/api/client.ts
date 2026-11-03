/**
 * @file Shared axios instance for every API call, plus list-paging helpers.
 *
 * `withCredentials` is what carries the Flask session cookie, so authenticated
 * requests work without any token handling in the client. Every request also sends
 * `X-Requested-With: XMLHttpRequest`, which the backend requires on any request that
 * changes data: a form on another site cannot set it, so a forged request fails.
 * Two response interceptors run on every failure: one copies the backend's `{ error }`
 * text into `error.message`, from a blob body too, the other reports a lost session to
 * whoever registered through {@link setUnauthorizedHandler}.
 */

import axios, { type AxiosError } from 'axios'

import type { PaginatedResponse } from '../types/pagination'

/** Largest page the API will serve; matches the backend's `per_page` ceiling. */
export const MAX_PER_PAGE = 100

/** The body every backend error response carries. */
interface ApiErrorBody {
    error?: string
}

/** Callback run when a request outside the sign-in steps is refused with 401. */
type UnauthorizedHandler = () => void

const client = axios.create({
    baseURL: '/api',
    timeout: 15_000,
    withCredentials: true,
    headers: {
        'Content-Type': 'application/json',
        'X-Requested-With': 'XMLHttpRequest',
    },
})

let unauthorizedHandler: UnauthorizedHandler | null = null

/**
 * Register the callback that runs when the server reports a lost session.
 *
 * The auth store registers itself here, so this module never imports the
 * store and the dependency graph stays acyclic.
 *
 * @param handler - The callback to run on a 401, or null to unregister it.
 */
export function setUnauthorizedHandler(handler: UnauthorizedHandler | null): void {
    unauthorizedHandler = handler
}

/**
 * Read the body of a failed response, which a blob request receives as a blob.
 *
 * A blob that is not JSON, such as a proxy's HTML error page, counts as no body.
 *
 * @param data - The response body, if there was one.
 * @returns The parsed body, or undefined when there is none to read.
 */
async function readErrorBody(
    data?: ApiErrorBody | Blob,
): Promise<ApiErrorBody | undefined> {
    if (!(data instanceof Blob)) {
        return data
    }
    try {
        return JSON.parse(await data.text()) as ApiErrorBody
    } catch {
        return undefined
    }
}

/**
 * Promote the backend's `{ error }` text to `error.message` so forms can show it.
 *
 * @param error - The rejection axios produced for a failed request.
 * @returns A promise rejected with the same error.
 */
export async function surfaceApiError(
    error: AxiosError<ApiErrorBody | Blob>,
): Promise<never> {
    const body = await readErrorBody(error.response?.data)
    const message = body?.error
    if (typeof message === 'string') {
        error.message = message
    }
    return Promise.reject(error)
}

/** Under `/v1/auth/`, the routes of a signed-in account, whose 401 is a lost session. */
const SIGNED_IN_AUTH_PATHS = ['/v1/auth/oauth', '/v1/auth/passkeys']

/** The passkey sign-in, whose 401 is a refused passkey, as a wrong password is. */
const PASSKEY_SIGN_IN_PATH = '/v1/auth/passkeys/login'

/**
 * Tell whether a URL is a path or lies beneath it.
 *
 * @param url - The request URL, relative to the API base.
 * @param path - The path to compare with.
 * @returns True for the path itself and anything under it.
 */
function isUnder(url: string, path: string): boolean {
    return url === path || url.startsWith(`${path}/`)
}

/**
 * Tell whether a 401 from a URL means a sign-in failed rather than a session was lost.
 *
 * Every `/v1/auth/` route is a sign-in step but the linked accounts and the passkeys,
 * which serve a signed-in account, and of those only the passkey sign-in is a step again.
 * The passkey list is `/v1/auth/passkeys` itself, with no trailing slash.
 *
 * @param url - The request URL, relative to the API base.
 * @returns True when the 401 is a form error, such as a wrong password.
 */
function isSignInStep(url: string | undefined): boolean {
    if (!url?.startsWith('/v1/auth/')) return false
    if (isUnder(url, PASSKEY_SIGN_IN_PATH)) return true
    return !SIGNED_IN_AUTH_PATHS.some((path) => isUnder(url, path))
}

/**
 * Run the registered handler when a request was refused for want of a session.
 *
 * A 401 from a sign-in step is skipped: a wrong password or a refused passkey is a form
 * error, not a lost session. The linked accounts under `/v1/auth/oauth/` and the passkeys
 * under `/v1/auth/passkeys` are ordinary signed-in requests, so their 401 counts.
 *
 * @param error - The rejection axios produced for a failed request.
 * @returns A promise rejected with the same error.
 */
function reportLostSession(error: AxiosError): Promise<never> {
    if (error.response?.status === 401 && !isSignInStep(error.config?.url)) {
        unauthorizedHandler?.()
    }
    return Promise.reject(error)
}

client.interceptors.response.use((response) => response, surfaceApiError)
client.interceptors.response.use((response) => response, reportLostSession)

/**
 * Fetch one page of a paginated list endpoint.
 *
 * @param url - The list endpoint, relative to the API base.
 * @param page - The 1-based page number to request.
 * @param params - Extra query parameters merged into the request.
 * @returns The page envelope: the items plus the pagination metadata.
 */
export async function fetchPage<T>(
    url: string,
    page: number,
    params: Record<string, unknown> = {},
): Promise<PaginatedResponse<T>> {
    const { data } = await client.get<PaginatedResponse<T>>(url, {
        params: { ...params, page, per_page: MAX_PER_PAGE },
    })
    return data
}

/**
 * Page through a paginated list endpoint and return every item.
 *
 * Stops after a short page, or once the collected count reaches the total the
 * server reports, whichever comes first.
 *
 * @param url - The list endpoint, relative to the API base.
 * @param params - Extra query parameters merged into every page request.
 * @returns Every item across all pages, in server order.
 */
export async function fetchAll<T>(
    url: string,
    params: Record<string, unknown> = {},
): Promise<T[]> {
    const items: T[] = []
    let page = 1
    let done = false
    while (!done) {
        const body = await fetchPage<T>(url, page, params)
        items.push(...body.items)
        done = body.items.length < MAX_PER_PAGE || items.length >= body.total
        page += 1
    }
    return items
}

export default client
