import { act, renderHook } from '@testing-library/react'
import { AxiosError } from 'axios'
import { describe, expect, it } from 'vitest'

import { useApiError } from '../hooks/useApiError'

describe('useApiError', () => {
    it('starts with no error', () => {
        const { result } = renderHook(() => useApiError())

        expect(result.current.error).toBeNull()
    })

    it('records the message of an Error', () => {
        const { result } = renderHook(() => useApiError())

        act(() => result.current.onErr(new Error('oops')))

        expect(result.current.error).toBe('oops')
    })

    it('records the message the client interceptor left on an AxiosError', () => {
        const { result } = renderHook(() => useApiError())
        const error = new AxiosError('Invalid email or password.')

        act(() => result.current.onErr(error))

        expect(result.current.error).toBe('Invalid email or password.')
    })

    it('falls back to the default message for a value that is not an Error', () => {
        const { result } = renderHook(() => useApiError())

        act(() => result.current.onErr('string error'))

        expect(result.current.error).toBe('An unexpected error occurred.')
    })

    it('uses the caller-supplied default message', () => {
        const { result } = renderHook(() => useApiError('Custom default.'))

        act(() => result.current.onErr({ response: { status: 500 } }))

        expect(result.current.error).toBe('Custom default.')
    })

    it('clearError resets the message to null', () => {
        const { result } = renderHook(() => useApiError())

        act(() => result.current.onErr(new Error('oops')))
        act(() => result.current.clearError())

        expect(result.current.error).toBeNull()
    })
})
