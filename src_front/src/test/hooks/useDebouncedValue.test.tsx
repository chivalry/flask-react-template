/** @file Check that only a settled value is published and unmount cancels the timer. */

import { act, renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { useDebouncedValue } from '../../hooks/useDebouncedValue'

describe('useDebouncedValue', () => {
    afterEach(() => vi.useRealTimers())

    it('publishes only the settled value and cancels timers on unmount', () => {
        vi.useFakeTimers()
        const { result, rerender, unmount } = renderHook(
            ({ value }) => useDebouncedValue(value, 300),
            { initialProps: { value: 'A' } },
        )
        rerender({ value: 'Ad' })
        act(() => vi.advanceTimersByTime(200))
        rerender({ value: 'Ada' })
        act(() => vi.advanceTimersByTime(299))
        expect(result.current).toBe('A')
        act(() => vi.advanceTimersByTime(1))
        expect(result.current).toBe('Ada')
        rerender({ value: 'Grace' })
        unmount()
        expect(vi.getTimerCount()).toBe(0)
    })
})
