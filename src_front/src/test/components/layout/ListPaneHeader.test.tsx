/** @file A list pane's heading, its announced record count, and its action slot. */

import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import ListPaneHeader from '../../../components/layout/ListPaneHeader'

const NOUNS = { one: 'user', other: 'users' }

describe('ListPaneHeader', () => {
    it('titles the pane with a level-one heading and renders its action', () => {
        render(
            <ListPaneHeader
                title="Users"
                count={2}
                nouns={NOUNS}
                action={<button>New user</button>}
            />,
        )

        expect(
            screen.getByRole('heading', { level: 1, name: 'Users' }),
        ).toBeInTheDocument()
        expect(screen.getByRole('button', { name: 'New user' })).toBeInTheDocument()
    })

    it('renders no button without an action', () => {
        render(<ListPaneHeader title="Users" count={2} nouns={NOUNS} />)

        expect(screen.queryByRole('button')).toBeNull()
    })

    it.each([
        [0, '0 users'],
        [1, '1 user'],
        [1234, '1,234 users'],
    ])('announces a count of %i as "%s"', (count, text) => {
        render(<ListPaneHeader title="Users" count={count} nouns={NOUNS} />)

        expect(screen.getByRole('status').textContent).toBe(text)
    })

    it('hides the noun from sight, not from screen readers', () => {
        render(<ListPaneHeader title="Users" count={3} nouns={NOUNS} />)

        expect(screen.getByText('users')).toHaveStyle({
            position: 'absolute',
            width: '1px',
            height: '1px',
            overflow: 'hidden',
        })
        expect(screen.getByRole('heading', { level: 1 })).not.toHaveTextContent('3')
    })

    it('keeps the status region mounted while the count loads', () => {
        const { rerender } = render(
            <ListPaneHeader title="Users" count={undefined} nouns={NOUNS} />,
        )
        const status = screen.getByRole('status')
        expect(status).toBeEmptyDOMElement()

        rerender(<ListPaneHeader title="Users" count={3} nouns={NOUNS} />)

        expect(screen.getByRole('status')).toBe(status)
        expect(status.textContent).toBe('3 users')
    })
})
