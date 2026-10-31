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

/** Callback run when a request outside the auth endpoints is refused with 401. */
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

/**
 * Run the registered handler when a request was refused for want of a session.
 *
 * A 401 from the auth endpoints themselves is skipped: a wrong password is a
 * form error, not a lost session.
 *
 * @param error - The rejection axios produced for a failed request.
 * @returns A promise rejected with the same error.
 */
function reportLostSession(error: AxiosError): Promise<never> {
    const url = error.config?.url
    if (error.response?.status === 401 && !url?.startsWith('/v1/auth/')) {
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
