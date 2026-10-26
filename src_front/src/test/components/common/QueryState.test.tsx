/** @file Check the spinner, error, and content QueryState shows for each query state. */
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import QueryState from '../../../components/common/QueryState'

describe('QueryState', () => {
    it('shows the error message of a failed query', () => {
        render(
            <QueryState
                query={{
                    isPending: false,
                    isError: true,
                    error: new Error('Network down.'),
                    data: undefined,
                }}
            >
                {() => <span>Loaded</span>}
            </QueryState>,
        )
        expect(screen.getByRole('alert')).toHaveTextContent('Network down.')
        expect(screen.queryByText('Loaded')).not.toBeInTheDocument()
    })
    it('shows a fallback message when a failed query has no error object', () => {
        render(
            <QueryState
                query={{ isPending: false, isError: true, error: null, data: undefined }}
            >
                {() => <span>Loaded</span>}
            </QueryState>,
        )
        expect(screen.getByRole('alert')).toHaveTextContent('Something went wrong.')
    })
    it('shows a spinner while the query is pending', () => {
        render(
            <QueryState
                query={{ isPending: true, isError: false, error: null, data: undefined }}
            >
                {() => <span>Loaded</span>}
            </QueryState>,
        )
        expect(screen.getByRole('progressbar')).toBeInTheDocument()
        expect(screen.queryByText('Loaded')).not.toBeInTheDocument()
    })
    it('waits when a settled query still has no data', () => {
        render(
            <QueryState
                query={{ isPending: false, isError: false, error: null, data: undefined }}
            >
                {() => <span>Loaded</span>}
            </QueryState>,
        )
        expect(screen.getByRole('progressbar')).toBeInTheDocument()
    })
    it('renders the children with the loaded data', () => {
        render(
            <QueryState
                query={{
                    isPending: false,
                    isError: false,
                    error: null,
                    data: ['Ada', 'Grace'],
                }}
            >
                {(names) => <span>{names.join(', ')}</span>}
            </QueryState>,
        )
        expect(screen.getByText('Ada, Grace')).toBeInTheDocument()
        expect(screen.queryByRole('progressbar')).not.toBeInTheDocument()
        expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    })
})
