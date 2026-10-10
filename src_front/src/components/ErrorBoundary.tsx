/** @file Top-level error boundary wrapping the whole application tree. */

import { Alert, Button, Box } from '@mui/material'
import { Component, ErrorInfo, ReactNode } from 'react'

/** Props accepted by {@link ErrorBoundary}. */
interface Props {
    children: ReactNode
}

/** Internal state of {@link ErrorBoundary}. */
interface State {
    hasError: boolean
}

/**
 * Catch render-time errors in the subtree and show a recoverable alert.
 *
 * Only catches errors thrown during rendering, lifecycle methods, and
 * constructors below it. Errors thrown in event handlers and async callbacks
 * do not reach a boundary and must be handled where they occur.
 */
export default class ErrorBoundary extends Component<Props, State> {
    state: State = { hasError: false }

    /**
     * Flip the boundary into its error state when a descendant throws.
     *
     * @returns The next state, with the error flag set.
     */
    static getDerivedStateFromError(): State {
        return { hasError: true }
    }

    /**
     * Log an uncaught render error and the component stack that produced it.
     *
     * @param error - The error thrown by a descendant component.
     * @param info - React's component stack for the failing subtree.
     */
    componentDidCatch(error: Error, info: ErrorInfo) {
        // eslint-disable-next-line no-console
        console.error('Uncaught error:', error, info)
    }

    /**
     * Render the fallback alert while in the error state, else the children.
     *
     * @returns The fallback alert, or the wrapped subtree.
     */
    render() {
        if (this.state.hasError) {
            return (
                <Box sx={{ p: 4 }}>
                    <Alert
                        severity="error"
                        action={
                            <Button
                                color="inherit"
                                size="small"
                                onClick={() => this.setState({ hasError: false })}
                            >
                                Try again
                            </Button>
                        }
                    >
                        Something went wrong.
                    </Alert>
                </Box>
            )
        }
        return this.props.children
    }
}
