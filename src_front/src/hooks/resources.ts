/** @file Mutations for top-level resources that keep their cached queries current. */

import { useMutation, useQueryClient } from '@tanstack/react-query'
import type { QueryKey } from '@tanstack/react-query'

import type { ResourceApi } from '../api/resources'

/** What {@link useResourceMutations} does beyond invalidating the resource's key. */
interface ResourceMutationOptions<TRecord> {
    /** Further keys to invalidate on success, such as another resource's list. */
    alsoInvalidate?: QueryKey[]
    /** Receives each record an update saves, such as to refresh another copy of it. */
    onUpdated?: (record: TRecord) => void
}

/**
 * Build create, update, and remove mutations for one top-level resource.
 *
 * A record's detail query, where the resource has one, is keyed `[...key, id]`, so
 * invalidating `key` refreshes the list and every detail by prefix; `remove` drops
 * the deleted record's detail query instead.
 *
 * @param key - The resource's cache key.
 * @param api - The resource's API functions.
 * @param options - Further keys to invalidate on success, and a callback for each
 *   record an update saves.
 * @returns The three mutations.
 */
export function useResourceMutations<TRecord, TPayload>(
    key: QueryKey,
    api: ResourceApi<TRecord, TPayload>,
    options: ResourceMutationOptions<TRecord> = {},
) {
    const { alsoInvalidate = [], onUpdated } = options
    const queryClient = useQueryClient()
    /** Invalidate the resource's queries and every extra key. */
    const invalidate = () => {
        for (const queryKey of [key, ...alsoInvalidate]) {
            void queryClient.invalidateQueries({ queryKey })
        }
    }
    const create = useMutation({
        mutationFn: (payload: TPayload) => api.create(payload),
        onSuccess: invalidate,
    })
    const update = useMutation({
        mutationFn: ({ id, payload }: { id: number; payload: TPayload }) =>
            api.update(id, payload),
        onSuccess: (record) => {
            invalidate()
            onUpdated?.(record)
        },
    })
    const remove = useMutation({
        mutationFn: (id: number) => api.remove(id),
        onSuccess: (_data, id) => {
            // Invalidating the list would refetch the detail query `[...key, id]` by
            // prefix, showing the deleted record from cache through the retries.
            queryClient.removeQueries({ queryKey: [...key, id] })
            invalidate()
        },
    })
    return { create, update, remove }
}
