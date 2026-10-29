/** @file DetailHeader shows its title and subtitle, and a button for each handler. */

import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import DetailHeader from '../../../components/common/DetailHeader'

describe('DetailHeader', () => {
    it('shows the title as a level-one heading, with the subtitle', () => {
        render(<DetailHeader title="ada@example.com" subtitle="Administrator" />)

        expect(
            screen.getByRole('heading', { level: 1, name: 'ada@example.com' }),
        ).toBeInTheDocument()
        expect(screen.getByText('Administrator')).toBeInTheDocument()
    })

    it.each([undefined, null])(
        'keeps only the title in its box when the subtitle is %s',
        (subtitle) => {
            render(<DetailHeader title="ada@example.com" subtitle={subtitle} />)

            expect(
                screen.getByRole('heading', { level: 1 }).parentElement,
            ).toHaveProperty('childElementCount', 1)
        },
    )

    it('calls each handler once when its button is clicked', async () => {
        const user = userEvent.setup()
        const onEdit = vi.fn()
        const onDelete = vi.fn()
        render(<DetailHeader title="Ada" onEdit={onEdit} onDelete={onDelete} />)

        await user.click(screen.getByRole('button', { name: 'Edit' }))

        expect(onEdit).toHaveBeenCalledOnce()
        expect(onDelete).not.toHaveBeenCalled()

        await user.click(screen.getByRole('button', { name: 'Delete' }))

        expect(onEdit).toHaveBeenCalledOnce()
        expect(onDelete).toHaveBeenCalledOnce()
    })

    it('offers no Delete button when only onEdit is given', () => {
        render(<DetailHeader title="Ada" onEdit={vi.fn()} />)

        expect(screen.getByRole('button', { name: 'Edit' })).toBeInTheDocument()
        expect(screen.queryByRole('button', { name: 'Delete' })).not.toBeInTheDocument()
    })

    it('offers no buttons when neither handler is given', () => {
        render(<DetailHeader title="Ada" />)

        expect(screen.queryAllByRole('button')).toEqual([])
    })

    it('lets a long title shrink and break inside a word', () => {
        render(<DetailHeader title="a.very.long.address@example.com" onEdit={vi.fn()} />)

        expect(screen.getByRole('heading', { level: 1 }).parentElement).toHaveStyle({
            minWidth: '0px',
            overflowWrap: 'break-word',
        })
    })
})
