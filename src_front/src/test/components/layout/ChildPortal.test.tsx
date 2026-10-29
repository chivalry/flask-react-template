/** @file Tabs from sm up, a select below it, and one child list mounted at a time. */

import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'

import ChildPortal from '../../../components/layout/ChildPortal'
import { stubViewportWidth } from '../../utils/viewport'

const TABS = [
    { value: 'history', label: 'History', content: <p>History list</p> },
    { value: 'activity', label: 'Activity', content: <p>Activity list</p> },
]

/** A controlled portal whose tab lives in local state, as a page keeps it. */
function Harness({ initialValue = '' }: { initialValue?: string }) {
    const [value, setValue] = useState(initialValue)
    return (
        <ChildPortal
            label="Account history"
            tabs={TABS}
            value={value}
            onChange={setValue}
        />
    )
}

/** A portal over the given tabs, with a value the caller fixes. */
const portal = (tabs: typeof TABS, value: string) => (
    <ChildPortal label="Account history" tabs={tabs} value={value} onChange={vi.fn()} />
)

describe('ChildPortal', () => {
    it('selects the first tab for an empty value and mounts only its list', () => {
        render(<Harness />)

        expect(
            screen.getByRole('tablist', { name: 'Account history' }),
        ).toBeInTheDocument()
        expect(screen.getByRole('tab', { name: 'History' })).toHaveAttribute(
            'aria-selected',
            'true',
        )
        const panel = screen.getByRole('tabpanel', { name: 'History' })
        expect(panel).toHaveTextContent('History list')
        expect(screen.queryByText('Activity list')).not.toBeInTheDocument()
        // Each tab names the panel it controls, which needs an id to be named by.
        expect(panel.id).not.toBe('')
        for (const tab of screen.getAllByRole('tab')) {
            expect(tab).toHaveAttribute('aria-controls', panel.id)
        }
    })

    it('shows a clicked tab and unmounts the list it replaces', async () => {
        const user = userEvent.setup()
        render(<Harness />)

        await user.click(screen.getByRole('tab', { name: 'Activity' }))

        expect(screen.getByText('Activity list')).toBeInTheDocument()
        expect(screen.queryByText('History list')).not.toBeInTheDocument()
    })

    it('falls back to the first tab when the value matches none', async () => {
        const { rerender } = render(portal(TABS, 'activity'))
        expect(screen.getByText('Activity list')).toBeInTheDocument()

        rerender(portal([TABS[0]], 'activity'))
        // MUI's Tabs reacts to a removed tab in a microtask; settle it inside act.
        await act(() => Promise.resolve())

        expect(screen.getByText('History list')).toBeInTheDocument()
    })

    it.each([
        [600, 1, 0],
        [599, 0, 1],
    ])('at %i px it shows %i tab lists and %i selects', (width, tablists, selects) => {
        stubViewportWidth(width)
        render(<Harness />)

        expect(screen.queryAllByRole('tablist')).toHaveLength(tablists)
        expect(screen.queryAllByRole('combobox')).toHaveLength(selects)
    })

    it('swaps the tabs for a labeled select at 375 px', async () => {
        stubViewportWidth(375)
        const user = userEvent.setup()
        render(<Harness />)

        expect(screen.queryByRole('tablist')).not.toBeInTheDocument()
        // Without a tab list the panel is a plain box, with no tab to be named by.
        expect(screen.queryByRole('tabpanel')).not.toBeInTheDocument()
        expect(screen.getByText('History list').parentElement).not.toHaveAttribute(
            'aria-labelledby',
        )
        const select = screen.getByRole('combobox', { name: /Account history/ })
        expect(select).toHaveTextContent('History')
        await user.click(select)
        await user.click(screen.getByRole('option', { name: 'Activity' }))

        expect(screen.getByText('Activity list')).toBeInTheDocument()
    })

    it('renders nothing without tabs', () => {
        const { container } = render(portal([], ''))

        expect(container).toBeEmptyDOMElement()
    })
})
