/** @file Make media queries answer as a viewport of a chosen width would. */

import { vi } from 'vitest'

/**
 * Tell whether a media query's width conditions hold at a viewport width.
 *
 * Only `min-width` and `max-width` in pixels are read, which is all that MUI's
 * `breakpoints.up()` and `breakpoints.down()` produce.
 */
function matchesWidth(query: string, width: number): boolean {
    const min = /min-width:\s*([\d.]+)px/.exec(query)
    const max = /max-width:\s*([\d.]+)px/.exec(query)
    return (!min || width >= Number(min[1])) && (!max || width <= Number(max[1]))
}

/**
 * Stub `window.matchMedia` so MUI's `useMediaQuery` sees a viewport `width` pixels
 * wide.
 *
 * jsdom has no `matchMedia`, and without one `useMediaQuery` reports no match.
 * `test/setup.ts` stubs 1280 before every test; a test of a phone layout calls this
 * with 375 before it renders. The stub never fires a change event.
 */
export function stubViewportWidth(width: number) {
    vi.stubGlobal('matchMedia', (query: string) => ({
        matches: matchesWidth(query, width),
        media: query,
        addEventListener: () => undefined,
        removeEventListener: () => undefined,
    }))
}
