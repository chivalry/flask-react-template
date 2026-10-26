/** @file Check that the writer sets or deletes one parameter and replaces history. */

import { act, renderHook, screen } from '@testing-library/react'
import type { ReactNode } from 'react'
import { MemoryRouter, useLocation, useNavigationType } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import { useSearchParamWriter } from '../../hooks/useSearchParamWriter'

/** Show the current query string and how the router reached the current entry. */
function LocationProbe() {
    const { search } = useLocation()
    const navigationType = useNavigationType()
    return (
        <>
            <output aria-label="Search">{search}</output>
            <output aria-label="Navigation type">{navigationType}</output>
        </>
    )
}

/** Mount the writer in a memory router that starts at `url`, beside the probe. */
function renderWriter(url: string) {
    return renderHook(() => useSearchParamWriter(), {
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
})
