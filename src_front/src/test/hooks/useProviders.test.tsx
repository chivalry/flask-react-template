/** @file The enabled providers load once, and a failure leaves the list empty. */

import { renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { listProviders } from '../../api/oauth'
import { useProviders } from '../../hooks/useProviders'
import { googleProvider } from '../utils/fixtures'

vi.mock('../../api/oauth')

describe('useProviders', () => {
    beforeEach(() => {
        vi.clearAllMocks()
    })

    it('starts empty, then holds the providers once they load', async () => {
        vi.mocked(listProviders).mockResolvedValue([googleProvider])

        const { result } = renderHook(() => useProviders())

        expect(result.current).toEqual([])
        await waitFor(() => expect(result.current).toEqual([googleProvider]))
    })

    it('stays empty after a failure, leaving no unhandled rejection', async () => {
        const onUnhandledRejection = vi.fn()
        process.on('unhandledRejection', onUnhandledRejection)
        vi.mocked(listProviders).mockRejectedValue(new Error('Network Error'))

        try {
            const { result } = renderHook(() => useProviders())
            await waitFor(() => expect(listProviders).toHaveBeenCalledTimes(1))
            // Node reports a rejection nothing handled once the microtasks have run.
            await new Promise((resolve) => setTimeout(resolve, 0))

            expect(result.current).toEqual([])
            expect(onUnhandledRejection).not.toHaveBeenCalled()
        } finally {
            process.off('unhandledRejection', onUnhandledRejection)
        }
    })

    it('fetches once across a rerender', async () => {
        vi.mocked(listProviders).mockResolvedValue([googleProvider])
        const { result, rerender } = renderHook(() => useProviders())
        await waitFor(() => expect(result.current).toEqual([googleProvider]))

        rerender()

        expect(result.current).toEqual([googleProvider])
        expect(listProviders).toHaveBeenCalledTimes(1)
    })
})
