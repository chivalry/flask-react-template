/** @file Both panes show from md up; below it one shows at a time, with Back. */

import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { beforeEach, describe, expect, it } from 'vitest'

import MasterDetailLayout from '../../../components/layout/MasterDetailLayout'
import { stubViewportWidth } from '../../utils/viewport'

/** A list of one record, Ada, whose selection lives in local state. */
function Harness({ selectedAtFirst = false }: { selectedAtFirst?: boolean }) {
    const [selected, setSelected] = useState(selectedAtFirst)
    return (
        <MasterDetailLayout
            list={<button onClick={() => setSelected(true)}>Ada</button>}
            detail={<h2>Ada's details</h2>}
            showDetail={selected}
            onBack={() => setSelected(false)}
            emptyState={<p>Pick someone.</p>}
        />
    )
}

/** The list pane, the parent of Ada's row. */
const listPane = () => screen.getByText('Ada').parentElement!

describe('MasterDetailLayout', () => {
    it('shows the list and the empty state side by side at 1280 px', () => {
        render(<Harness />)

        expect(listPane()).toBeVisible()
        expect(listPane()).toHaveStyle({ width: '384px' })
        expect(screen.getByText('Pick someone.')).toBeVisible()
        expect(screen.queryByRole('button', { name: 'Back' })).not.toBeInTheDocument()
    })

    it('shows a clicked record beside the list and leaves focus on its row', async () => {
        const user = userEvent.setup()
        render(<Harness />)

        await user.click(screen.getByRole('button', { name: 'Ada' }))

        expect(screen.getByRole('heading', { name: "Ada's details" })).toBeVisible()
        expect(listPane()).toBeVisible()
        expect(screen.getByRole('button', { name: 'Ada' })).toHaveFocus()
        expect(screen.queryByRole('button', { name: 'Back' })).not.toBeInTheDocument()
    })

    it.each([
        [900, true],
        [899, false],
    ])('at %i px the empty state shows beside the list: %s', (width, beside) => {
        stubViewportWidth(width)
        render(<Harness />)

        expect(listPane()).toBeVisible()
        if (beside) {
            expect(screen.getByText('Pick someone.')).toBeVisible()
        } else {
            expect(screen.getByText('Pick someone.')).not.toBeVisible()
        }
    })

    describe('at 375 px', () => {
        beforeEach(() => {
            stubViewportWidth(375)
        })

        it('shows only the list until a record is selected', () => {
            render(<Harness />)

            expect(listPane()).toBeVisible()
            expect(listPane()).toHaveStyle({ width: '100%' })
            expect(screen.getByText('Pick someone.')).not.toBeVisible()
        })

        it('swaps the list for the record and Back, moving focus to it', async () => {
            const user = userEvent.setup()
            render(<Harness />)

            await user.click(screen.getByRole('button', { name: 'Ada' }))

            const heading = screen.getByRole('heading', { name: "Ada's details" })
            expect(screen.getByText('Ada')).not.toBeVisible()
            expect(heading).toBeVisible()
            expect(screen.getByRole('button', { name: 'Back' })).toBeVisible()
            expect(heading.parentElement).toHaveFocus()
        })

        it('returns to the list with Back and focuses the list pane', async () => {
            const user = userEvent.setup()
            render(<Harness />)
            await user.click(screen.getByRole('button', { name: 'Ada' }))

            await user.click(screen.getByRole('button', { name: 'Back' }))

            expect(screen.getByText('Ada')).toBeVisible()
            expect(screen.getByText('Pick someone.')).not.toBeVisible()
            expect(listPane()).toHaveFocus()
        })

        it('shows a record selected at first without moving focus', () => {
            render(<Harness selectedAtFirst />)

            expect(screen.getByRole('heading', { name: "Ada's details" })).toBeVisible()
            expect(document.body).toHaveFocus()
        })
    })
})
