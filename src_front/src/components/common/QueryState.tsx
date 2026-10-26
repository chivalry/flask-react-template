/** @file Spinner, error alert, or content, depending on a query's state. */

import { Alert, Box, CircularProgress } from '@mui/material'
import type { ReactNode } from 'react'

/** The parts of a TanStack query that {@link QueryState} reads. */
interface QueryLike<T> {
    isPending: boolean
    isError: boolean
    error: Error | null
    data: T | undefined
}

/** Props accepted by {@link QueryState}. */
interface QueryStateProps<T> {
    query: QueryLike<T>
    children: (data: T) => ReactNode
}

/**
 * Render a spinner while loading, the error when the query failed, and
 * otherwise the children with the loaded data.
 *
 * @param props - The component props.
 * @returns The element for the query's current state.
 */
export default function QueryState<T>(props: QueryStateProps<T>) {
    const { query, children } = props
    if (query.isError) {
        return (
            <Alert severity="error" sx={{ m: 2 }}>
                {query.error ? query.error.message : 'Something went wrong.'}
            </Alert>
        )
    }
    if (query.isPending || query.data === undefined) {
        return (
            <Box sx={{ display: 'flex', justifyContent: 'center', p: 3 }}>
                <CircularProgress />
            </Box>
        )
    }
    return <>{children(query.data)}</>
}
