/** @file Endpoints for top-level resources, which share one CRUD shape. */

import client, { fetchAll } from './client'

/** The operations a top-level resource supports. */
export interface ResourceApi<TRecord, TPayload> {
    list: () => Promise<TRecord[]>
    create: (payload: TPayload) => Promise<TRecord>
    update: (id: number, payload: TPayload) => Promise<TRecord>
    remove: (id: number) => Promise<void>
}

/**
 * Build the API functions for one top-level resource.
 *
 * @param path - The resource path under the API base, such as `/v1/users`.
 * @returns The list, create, update, and remove functions.
 */
export function resource<TRecord, TPayload>(
    path: string,
): ResourceApi<TRecord, TPayload> {
    return {
        list: () => fetchAll<TRecord>(path),
        create: async (payload) => (await client.post<TRecord>(path, payload)).data,
        update: async (id, payload) =>
            (await client.put<TRecord>(`${path}/${id}`, payload)).data,
        remove: async (id) => {
            await client.delete(`${path}/${id}`)
        },
    }
}
