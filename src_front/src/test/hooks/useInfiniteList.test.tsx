/** @file Page through a paginated endpoint and read the loaded pages back. */

import { act, renderHook, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import {
    flattenPages,
    lastLoadedPageTotal,
    useInfiniteList,
} from '../../hooks/useInfiniteList'
import type { PaginatedResponse } from '../../types/pagination'
import Providers from '../utils/Providers'

/** A list row; the hook never looks inside one. */
interface Item {
    id: number
}

/** Build one page of a list served 100 rows per page; its one row has the page's id. */
function listPage(page: number, total: number): PaginatedResponse<Item> {
    return {
        items: [{ id: page }],
        page,
        pages: Math.ceil(total / 100),
        per_page: 100,
        total,
    }
}

/**
 * Mount the hook over a list of `total` rows and wait for its first page. Each mount gets
 * a fresh, non-retrying query client.
 */
async function renderFirstPage(total: number) {
    const fetchPage = vi.fn((page: number) => Promise.resolve(listPage(page, total)))
    const { result } = renderHook(
        () => useInfiniteList({ queryKey: ['things'], fetchPage }),
        { wrapper: Providers },
    )
    await waitFor(() => expect(result.current.data?.pages).toHaveLength(1))
    return { fetchPage, result }
}

/** Mount the hook over a list of `total` rows and load the second page it offers. */
async function loadTwoPages(total: number) {
    const { fetchPage, result } = await renderFirstPage(total)
    expect(result.current.hasNextPage).toBe(true)
    await act(async () => {
        await result.current.fetchNextPage()
    })
    await waitFor(() => expect(result.current.data?.pages).toHaveLength(2))
    return { fetchPage, result }
}

describe('useInfiniteList', () => {
    it('fetches the first page with 1', async () => {
        const { fetchPage, result } = await renderFirstPage(1)

        expect(result.current.data?.pages).toEqual([listPage(1, 1)])
        expect(fetchPage).toHaveBeenCalledExactlyOnceWith(1)
    })

    it('reports a next page, fetches it with 2, and flattens both in order', async () => {
        const { fetchPage, result } = await loadTwoPages(150)

        expect(fetchPage).toHaveBeenLastCalledWith(2)
        expect(flattenPages(result.current.data)).toEqual([{ id: 1 }, { id: 2 }])
    })

    it('reports no next page on the final page', async () => {
        const { result } = await renderFirstPage(1)

        expect(result.current.hasNextPage).toBe(false)
    })

    it('reports no next page when the final page is exactly full', async () => {
        const { fetchPage, result } = await loadTwoPages(200)

        expect(result.current.hasNextPage).toBe(false)
        expect(fetchPage).toHaveBeenCalledTimes(2)
    })
})

describe('flattenPages', () => {
    it('returns an empty array before the first page lands', () => {
        expect(flattenPages(undefined)).toEqual([])
    })
})

describe('lastLoadedPageTotal', () => {
    it('returns undefined before the first page lands', () => {
        expect(lastLoadedPageTotal(undefined)).toBeUndefined()
    })

    it('reads the total from the newest loaded page', () => {
        // A row was deleted between the two loads, so the pages disagree.
        const data = { pages: [listPage(1, 151), listPage(2, 150)], pageParams: [1, 2] }

        expect(lastLoadedPageTotal(data)).toBe(150)
    })
})
