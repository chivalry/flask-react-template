/** @file Infinite-scroll query over the API's pagination envelope. */

import { useInfiniteQuery } from '@tanstack/react-query'
import type { InfiniteData, QueryKey } from '@tanstack/react-query'

import type { PaginatedResponse } from '../types/pagination'

/** What {@link useInfiniteList} needs: a cache key and a page loader. */
interface UseInfiniteListOptions<T> {
    queryKey: QueryKey
    fetchPage: (page: number) => Promise<PaginatedResponse<T>>
}

/**
 * Load a paginated endpoint page by page as the viewer scrolls.
 *
 * @param options - The cache key and the function that loads one page.
 * @param options.queryKey - The cache key; include the filters so a change refetches.
 * @param options.fetchPage - Loads the given 1-based page.
 * @returns The infinite query, whose `data.pages` holds every page loaded so far.
 */
export function useInfiniteList<T>({ queryKey, fetchPage }: UseInfiniteListOptions<T>) {
    return useInfiniteQuery({
        queryKey,
        queryFn: ({ pageParam }) => fetchPage(pageParam),
        initialPageParam: 1,
        getNextPageParam: (lastPage) =>
            lastPage.page * lastPage.per_page < lastPage.total
                ? lastPage.page + 1
                : undefined,
    })
}

/**
 * Flatten an infinite query's pages into one item array.
 *
 * @param data - The query's data, or undefined before the first page lands.
 * @returns Every loaded item, in page order.
 */
export function flattenPages<T>(
    data: InfiniteData<PaginatedResponse<T>> | undefined,
): T[] {
    return data?.pages.flatMap((page) => page.items) ?? []
}

/**
 * Read the total from the newest loaded page.
 *
 * Every page carries the total. The last one loaded is the newest, and it is the
 * page that `getNextPageParam` above reads.
 *
 * @param data - The query's data, or undefined before the first page lands.
 * @returns The total, or undefined before the first page lands.
 */
export function lastLoadedPageTotal<T>(
    data: InfiniteData<PaginatedResponse<T>> | undefined,
): number | undefined {
    if (data === undefined) return undefined
    return data.pages[data.pages.length - 1].total
}
