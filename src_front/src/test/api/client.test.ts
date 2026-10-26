import { AxiosError, AxiosHeaders } from 'axios'
import type { AxiosAdapter, AxiosResponse, InternalAxiosRequestConfig } from 'axios'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import client, {
    MAX_PER_PAGE,
    fetchAll,
    fetchPage,
    setUnauthorizedHandler,
    surfaceApiError,
} from '../../api/client'

// Replace the network with an adapter that answers every request the same way.
// Statuses of 400 and up reject with an AxiosError, as the real adapters do, so
// the response interceptors run exactly as they would in the browser.
const respondWith =
    (status: number, data: unknown): AxiosAdapter =>
    async (config: InternalAxiosRequestConfig) => {
        const response: AxiosResponse = {
            data,
            status,
            statusText: '',
            headers: new AxiosHeaders(),
            config,
        }
        if (status >= 400) {
            throw new AxiosError(
                `Request failed with status code ${status}`,
                'ERR_BAD_REQUEST',
                config,
                undefined,
                response,
            )
        }
        return response
    }

const pageOf = (items: unknown[], total: number, page = 1) => ({
    data: {
        items,
        total,
        page,
        pages: Math.ceil(total / MAX_PER_PAGE),
        per_page: MAX_PER_PAGE,
    },
})

describe('api client', () => {
    it('targets the /api base URL', () => {
        expect(client.defaults.baseURL).toBe('/api')
    })

    it('sends cookies with requests', () => {
        expect(client.defaults.withCredentials).toBe(true)
    })

    it('times out after fifteen seconds', () => {
        expect(client.defaults.timeout).toBe(15000)
    })

    it('sends a JSON Content-Type header', () => {
        expect(client.defaults.headers['Content-Type']).toBe('application/json')
    })

    it('caps page size at the backend ceiling', () => {
        expect(MAX_PER_PAGE).toBe(100)
    })
})

describe('surfaceApiError', () => {
    it('copies the backend error text into the message', async () => {
        const error = {
            message: 'Request failed with status code 409',
            response: { data: { error: 'Email is already registered.' } },
        } as AxiosError<{ error?: string }>

        await expect(surfaceApiError(error)).rejects.toBe(error)
        expect(error.message).toBe('Email is already registered.')
    })

    it('leaves the message alone when the body carries no error text', async () => {
        const error = { message: 'Network Error' } as AxiosError<{ error?: string }>

        await expect(surfaceApiError(error)).rejects.toBe(error)
        expect(error.message).toBe('Network Error')
    })
})

describe('response interceptors', () => {
    const handler = vi.fn()

    beforeEach(() => {
        handler.mockClear()
        setUnauthorizedHandler(handler)
    })

    afterEach(() => {
        setUnauthorizedHandler(null)
    })

    it('pass a successful response through untouched', async () => {
        const response = await client.get('/v1/things', {
            adapter: respondWith(200, { items: [] }),
        })

        expect(response.status).toBe(200)
        expect(response.data).toEqual({ items: [] })
        expect(handler).not.toHaveBeenCalled()
    })

    it('surface the error text and report a lost session on a 401', async () => {
        await expect(
            client.get('/v1/things', {
                adapter: respondWith(401, { error: 'Session expired.' }),
            }),
        ).rejects.toThrow('Session expired.')

        expect(handler).toHaveBeenCalledTimes(1)
    })

    it('do not report a 401 from the auth endpoints', async () => {
        await expect(
            client.post(
                '/v1/auth/login',
                {},
                {
                    adapter: respondWith(401, { error: 'Invalid email or password.' }),
                },
            ),
        ).rejects.toThrow('Invalid email or password.')

        expect(handler).not.toHaveBeenCalled()
    })

    it('do not report other failures', async () => {
        await expect(
            client.get('/v1/things', {
                adapter: respondWith(500, { error: 'Something went wrong.' }),
            }),
        ).rejects.toThrow('Something went wrong.')

        expect(handler).not.toHaveBeenCalled()
    })

    it('still reject a 401 after the handler is unregistered', async () => {
        setUnauthorizedHandler(null)

        await expect(
            client.get('/v1/things', {
                adapter: respondWith(401, { error: 'Session expired.' }),
            }),
        ).rejects.toThrow('Session expired.')

        expect(handler).not.toHaveBeenCalled()
    })
})

describe('fetchPage', () => {
    afterEach(() => {
        vi.restoreAllMocks()
    })

    it('returns the requested page body', async () => {
        const body = pageOf([{ id: 3 }], 150, 2).data
        const get = vi.spyOn(client, 'get').mockResolvedValueOnce({ data: body })

        const result = await fetchPage('/v1/things', 2)

        expect(result).toEqual(body)
        expect(get).toHaveBeenCalledWith('/v1/things', {
            params: { page: 2, per_page: 100 },
        })
    })

    it('merges caller params into the page request', async () => {
        const get = vi.spyOn(client, 'get').mockResolvedValueOnce(pageOf([], 0))

        await fetchPage('/v1/things', 1, { owner_id: 4 })

        expect(get).toHaveBeenCalledWith('/v1/things', {
            params: { owner_id: 4, page: 1, per_page: 100 },
        })
    })
})

describe('fetchAll', () => {
    afterEach(() => {
        vi.restoreAllMocks()
    })

    it('returns every item from a single short page', async () => {
        const get = vi
            .spyOn(client, 'get')
            .mockResolvedValueOnce(pageOf([{ id: 1 }, { id: 2 }], 2))

        const result = await fetchAll('/v1/things')

        expect(result).toEqual([{ id: 1 }, { id: 2 }])
        expect(get).toHaveBeenCalledTimes(1)
        expect(get).toHaveBeenCalledWith('/v1/things', {
            params: { page: 1, per_page: 100 },
        })
    })

    it('follows pages until every item is collected', async () => {
        const firstPage = Array.from({ length: 100 }, (_, i) => ({ id: i }))
        const get = vi
            .spyOn(client, 'get')
            .mockResolvedValueOnce(pageOf(firstPage, 102, 1))
            .mockResolvedValueOnce(pageOf([{ id: 100 }, { id: 101 }], 102, 2))

        const result = await fetchAll('/v1/things')

        expect(result).toHaveLength(102)
        expect(get).toHaveBeenCalledTimes(2)
        expect(get).toHaveBeenLastCalledWith('/v1/things', {
            params: { page: 2, per_page: 100 },
        })
    })

    it('stops on a full final page once the total is reached', async () => {
        const page = Array.from({ length: 100 }, (_, i) => ({ id: i }))
        const get = vi.spyOn(client, 'get').mockResolvedValueOnce(pageOf(page, 100))

        const result = await fetchAll('/v1/things')

        expect(result).toHaveLength(100)
        expect(get).toHaveBeenCalledTimes(1)
    })

    it('merges caller params into each page request', async () => {
        const get = vi.spyOn(client, 'get').mockResolvedValueOnce(pageOf([], 0))

        await fetchAll('/v1/things', { owner_id: 5 })

        expect(get).toHaveBeenCalledWith('/v1/things', {
            params: { owner_id: 5, page: 1, per_page: 100 },
        })
    })
})
