/** @file Infinite scrolling requests and observer lifecycle tests. */

import { render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import InfiniteScrollSentinel from '../../../components/common/InfiniteScrollSentinel'

describe('InfiniteScrollSentinel', () => {
    afterEach(() => vi.unstubAllGlobals())

    it.each([
        [true, true, false, 1],
        [false, true, false, 0],
        [true, false, false, 0],
        [true, true, true, 0],
    ])(
        'intersection=%s, next=%s, fetching=%s requests %s pages',
        (isIntersecting, hasNextPage, isFetchingNextPage, requests) => {
            let callback: IntersectionObserverCallback = () => undefined
            const disconnect = vi.fn()
            const observe = vi.fn()
            const observer = { observe, disconnect } as unknown as IntersectionObserver
            vi.stubGlobal(
                'IntersectionObserver',
                class {
                    constructor(listener: IntersectionObserverCallback) {
                        callback = listener
                    }
                    observe = observe
                    disconnect = disconnect
                },
            )
            const fetchNextPage = vi.fn()
            const view = render(
                <InfiniteScrollSentinel
                    {...{ hasNextPage, isFetchingNextPage, fetchNextPage }}
                />,
            )
            expect(observe).toHaveBeenCalledWith(view.container.firstChild)
            callback([{ isIntersecting } as IntersectionObserverEntry], observer)
            expect(fetchNextPage).toHaveBeenCalledTimes(requests)
            expect(Boolean(screen.queryByRole('progressbar'))).toBe(isFetchingNextPage)
            view.unmount()
            expect(disconnect).toHaveBeenCalledOnce()
        },
    )
})
