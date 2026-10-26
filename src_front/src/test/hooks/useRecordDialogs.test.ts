/** @file Check the dialog state transitions of one record list. */
import { act, renderHook } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { useRecordDialogs } from '../../hooks/useRecordDialogs'

describe('useRecordDialogs', () => {
    it('opens each record dialog and clears all selection on close', () => {
        const { result } = renderHook(() => useRecordDialogs<{ id: number }>())
        act(() => result.current.openCreate())
        expect(result.current.creating).toBe(true)
        act(() => result.current.close())
        act(() => result.current.openEdit({ id: 1 }))
        expect(result.current.editing).toEqual({ id: 1 })
        act(() => result.current.close())
        act(() => result.current.openDelete({ id: 2 }))
        expect(result.current.deleting).toEqual({ id: 2 })
        act(() => result.current.close())
        expect(result.current).toMatchObject({
            creating: false,
            editing: null,
            deleting: null,
        })
    })
})
