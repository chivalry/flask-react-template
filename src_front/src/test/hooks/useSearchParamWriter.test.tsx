/**
 * @file Check that the writer sets, deletes, or leaves one parameter, replacing the
 * history entry unless it is built to push.
 */

import { act, renderHook, screen } from '@testing-library/react'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import { useSearchParamWriter } from '../../hooks/useSearchParamWriter'
import LocationProbe from '../utils/LocationProbe'

/**
 * Mount the writer, built with `options`, in a memory router that starts at `url`,
 * beside the probe.
 */
function renderWriter(url: string, options?: { push?: boolean }) {
    return renderHook(() => useSearchParamWriter(options), {
        wrapper: ({ children }: { children: ReactNode }) => (
            <MemoryRouter initialEntries={[url]}>
                {children}
                <LocationProbe />
            </MemoryRouter>
        ),
    })
}

/** Read the text of the probe output with the given accessible name. */
const probe = (label: string) => screen.getByLabelText(label).textContent

describe('useSearchParamWriter', () => {
    it('sets a parameter, keeps the others, and replaces the history entry', () => {
        const { result } = renderWriter('/people?other=keep')
        expect(probe('Navigation type')).toBe('POP')

        act(() => result.current('q', 'Ada'))

        expect(probe('Search')).toBe('?other=keep&q=Ada')
        expect(probe('Navigation type')).toBe('REPLACE')
    })

    it('deletes a parameter written empty and keeps the others', () => {
        const { result } = renderWriter('/people?q=Ada&other=keep')

        act(() => result.current('q', ''))

        expect(probe('Search')).toBe('?other=keep')
        expect(probe('Navigation type')).toBe('REPLACE')
    })

    it.each([
        {
            label: 'pushes a history entry when built to push',
            url: '/?tab=history',
            value: '2',
            search: '?tab=history&user=2',
            navigation: 'PUSH',
        },
        {
            label: 'writes nothing when the parameter already holds the value',
            url: '/?user=2',
            value: '2',
            search: '?user=2',
            navigation: 'POP',
        },
        {
            label: 'writes nothing when an absent parameter is cleared',
            url: '/?tab=history',
            value: '',
            search: '?tab=history',
            navigation: 'POP',
        },
    ])('$label', ({ url, value, search, navigation }) => {
        const { result } = renderWriter(url, { push: true })

        act(() => result.current('user', value))

        expect(probe('Search')).toBe(search)
        expect(probe('Navigation type')).toBe(navigation)
    })
})
