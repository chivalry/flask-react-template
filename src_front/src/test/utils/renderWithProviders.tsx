/** @file Render an element inside the test providers, optionally on a route. */

import { render } from '@testing-library/react'
import type { ReactElement } from 'react'
import { Route, Routes } from 'react-router-dom'

import Providers from './Providers'

/** Options for {@link renderWithProviders}. */
export interface RenderOptions {
    /** The URL the router starts at. */
    route?: string
    /** The route pattern the element is mounted on; defaults to every path. */
    path?: string
}

/**
 * Render an element inside the query client and router every screen expects.
 *
 * With `path` the element is mounted on that route pattern (so `useParams`
 * works); otherwise it renders on every path. Catch routes for `/` and `/login`
 * let tests assert navigation away from the element.
 */
export function renderWithProviders(ui: ReactElement, options: RenderOptions = {}) {
    const { route = '/', path } = options
    return render(
        <Providers route={route}>
            {path ? (
                <Routes>
                    <Route path={path} element={ui} />
                    <Route path="/" element={<div>Home route</div>} />
                    <Route path="/login" element={<div>Login route</div>} />
                </Routes>
            ) : (
                ui
            )}
        </Providers>,
    )
}
