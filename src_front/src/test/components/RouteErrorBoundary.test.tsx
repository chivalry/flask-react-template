import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Link, MemoryRouter, Route, Routes, useNavigate } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import RouteErrorBoundary from '../../components/RouteErrorBoundary'

const FALLBACK_TEXT = 'Something went wrong.'

// React's development build re-dispatches caught render errors as window error
// events; preventing their default stops jsdom from printing them to stderr.
const suppressWindowError = (event: ErrorEvent) => {
    event.preventDefault()
}

function ExplodingPage(): never {
    throw new Error('page explosion')
}

function BackButton() {
    const navigate = useNavigate()
    return <button onClick={() => navigate(-1)}>Back</button>
}

// The link and the Back button sit outside the routes, so a page error leaves them.
const renderRoutes = () =>
    render(
        <MemoryRouter initialEntries={['/boom']}>
            <Link to="/fine">Fine page link</Link>
            <BackButton />
            <Routes>
                <Route element={<RouteErrorBoundary />}>
                    <Route path="/boom" element={<ExplodingPage />} />
                    <Route path="/fine" element={<div>Fine page</div>} />
                </Route>
            </Routes>
        </MemoryRouter>,
    )

describe('RouteErrorBoundary', () => {
    beforeEach(() => {
        // React and the boundary both report the caught error through console.error.
        vi.spyOn(console, 'error').mockImplementation(() => undefined)
        window.addEventListener('error', suppressWindowError)
    })

    afterEach(() => {
        vi.restoreAllMocks()
        window.removeEventListener('error', suppressWindowError)
    })

    it('replaces only the failing page with the fallback', () => {
        renderRoutes()

        expect(screen.getByText(FALLBACK_TEXT)).toBeInTheDocument()
        expect(screen.getByRole('link', { name: 'Fine page link' })).toBeInTheDocument()
    })

    it('clears the fallback on navigation and shows it again on going back', async () => {
        const user = userEvent.setup()
        renderRoutes()

        await user.click(screen.getByRole('link', { name: 'Fine page link' }))

        expect(screen.getByText('Fine page')).toBeInTheDocument()
        expect(screen.queryByText(FALLBACK_TEXT)).not.toBeInTheDocument()

        await user.click(screen.getByRole('button', { name: 'Back' }))

        expect(screen.getByText(FALLBACK_TEXT)).toBeInTheDocument()
        expect(screen.queryByText('Fine page')).not.toBeInTheDocument()
    })
})
