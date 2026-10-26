/** @file Layout route that keeps a failing page from taking down the screen around it. */

import { Outlet, useLocation } from 'react-router-dom'

import ErrorBoundary from './ErrorBoundary'

/**
 * Render the matched child route inside an error boundary keyed to the pathname.
 *
 * Mounted as a pathless layout route, it stays mounted while the visitor moves between
 * the pages beneath it, so one instance serves them all: a page added later is covered
 * without wrapping it, and so is a lazy page whose chunk fails to load. Because the
 * instance outlives each page, the pathname is its reset key, which clears a caught
 * error when the visitor navigates to another page.
 *
 * @returns The matched child route inside the boundary.
 */
export default function RouteErrorBoundary() {
    const { pathname } = useLocation()
    return (
        <ErrorBoundary resetKey={pathname}>
            <Outlet />
        </ErrorBoundary>
    )
}
