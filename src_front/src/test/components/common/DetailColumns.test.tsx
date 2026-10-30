/** @file DetailColumns lists its left column first and lets each break long words. */

import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import DetailColumns from '../../../components/common/DetailColumns'

/** Render the columns with one heading in each. */
const renderColumns = () =>
    render(<DetailColumns left={<h2>Contact log</h2>} right={<h2>Addresses</h2>} />)

describe('DetailColumns', () => {
    it('reads the left column before the right one', () => {
        renderColumns()

        expect(
            screen.getAllByRole('heading').map((heading) => heading.textContent),
        ).toEqual(['Contact log', 'Addresses'])
    })

    it.each(['Contact log', 'Addresses'])(
        'lets the column holding %s shrink and break inside a word',
        (name) => {
            renderColumns()

            expect(screen.getByRole('heading', { name }).parentElement).toHaveStyle({
                minWidth: '0px',
                overflowWrap: 'break-word',
            })
        },
    )
})
