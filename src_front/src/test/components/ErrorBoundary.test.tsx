import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { MockInstance } from 'vitest'

import ErrorBoundary from '../components/ErrorBoundary'

let shouldThrow = false
let consoleErrorSpy: MockInstance<typeof console.error>

// React's development build re-dispatches caught render errors as window error
// events; preventing their default stops jsdom from printing them to stderr.
const suppressWindowError = (event: ErrorEvent) => {
    event.preventDefault()
}

function ControllableChild() {
    if (shouldThrow) {
        throw new Error('render explosion')
    }
    return <div>Child content</div>
}

describe('ErrorBoundary', () => {
    beforeEach(() => {
        shouldThrow = false
        window.addEventListener('error', suppressWindowError)
        // Both React and componentDidCatch report caught render errors through
        // console.error; silence them to keep test output clean.
        consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => undefined)
    })

    afterEach(() => {
        window.removeEventListener('error', suppressWindowError)
        vi.restoreAllMocks()
    })

    it('renders children when nothing throws', () => {
        render(
            <ErrorBoundary>
                <ControllableChild />
            </ErrorBoundary>,
        )

        expect(screen.getByText('Child content')).toBeInTheDocument()
        expect(screen.queryByText('Something went wrong.')).not.toBeInTheDocument()
    })

    it('renders the fallback alert when a child throws during render', () => {
        shouldThrow = true

        render(
            <ErrorBoundary>
                <ControllableChild />
            </ErrorBoundary>,
        )

        expect(screen.getByText('Something went wrong.')).toBeInTheDocument()
        expect(screen.queryByText('Child content')).not.toBeInTheDocument()
        expect(
            consoleErrorSpy.mock.calls.some((call) => call[0] === 'Uncaught error:'),
        ).toBe(true)
    })

    it('resets and re-renders children when Try again is clicked', async () => {
        const user = userEvent.setup()
        shouldThrow = true

        render(
            <ErrorBoundary>
                <ControllableChild />
            </ErrorBoundary>,
        )

        expect(screen.getByText('Something went wrong.')).toBeInTheDocument()

        shouldThrow = false
        await user.click(screen.getByRole('button', { name: 'Try again' }))

        expect(screen.getByText('Child content')).toBeInTheDocument()
        expect(screen.queryByText('Something went wrong.')).not.toBeInTheDocument()
    })
})
