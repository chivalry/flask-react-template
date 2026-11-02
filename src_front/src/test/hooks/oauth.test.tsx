/** @file The linked-account hooks load through the provider API and refresh on unlink. */

import { useQueryClient } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { listLinkedAccounts, unlinkAccount } from '../../api/oauth'
import { useLinkedAccounts, useUnlinkAccount } from '../../hooks/oauth'
import { linkedGoogleAccount } from '../utils/fixtures'
import Providers from '../utils/Providers'

vi.mock('../../api/oauth')

/** Render the unlink mutation beside the query client it reports to. */
const renderUnlinkAccount = () =>
    renderHook(() => ({ client: useQueryClient(), unlink: useUnlinkAccount() }), {
        wrapper: Providers,
    })

describe('linked-account hooks', () => {
    beforeEach(() => {
        vi.clearAllMocks()
    })

    it('useLinkedAccounts loads the links through listLinkedAccounts', async () => {
        vi.mocked(listLinkedAccounts).mockResolvedValue([linkedGoogleAccount])

        const { result } = renderHook(() => useLinkedAccounts(), { wrapper: Providers })

        await waitFor(() => expect(result.current.data).toEqual([linkedGoogleAccount]))
        expect(listLinkedAccounts).toHaveBeenCalledTimes(1)
    })

    it('useUnlinkAccount unlinks by name, then invalidates the links', async () => {
        vi.mocked(unlinkAccount).mockResolvedValue(undefined)
        const { result } = renderUnlinkAccount()
        const invalidateQueries = vi.spyOn(result.current.client, 'invalidateQueries')

        await act(async () => {
            await result.current.unlink.mutateAsync('google')
        })

        // TanStack Query passes the mutation's context as a second argument.
        expect(unlinkAccount).toHaveBeenCalledTimes(1)
        expect(vi.mocked(unlinkAccount).mock.calls[0][0]).toBe('google')
        expect(invalidateQueries.mock.calls).toEqual([
            [{ queryKey: ['linked-accounts'] }],
        ])
    })
})
