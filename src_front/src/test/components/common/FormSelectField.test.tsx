import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import FormSelectField from '../../../components/common/FormSelectField'
import FormHarness from '../../utils/FormHarness'

const ROLE_OPTIONS = [
    { value: 'admin', label: 'Admin' },
    { value: 'user', label: 'User' },
]

const onSubmit = vi.fn()

/** Open the dropdown; MUI labels the combobox with the label and the shown value. */
const openRoleSelect = async (user: ReturnType<typeof userEvent.setup>) => {
    await user.click(screen.getByRole('combobox', { name: /Role/ }))
}

describe('FormSelectField', () => {
    beforeEach(() => {
        vi.clearAllMocks()
    })

    it('lists the options and stores the chosen one in the form', async () => {
        const user = userEvent.setup()
        render(
            <FormHarness onSubmit={onSubmit} defaultValues={{ role: 'user' }}>
                <FormSelectField name="role" label="Role" options={ROLE_OPTIONS} />
            </FormHarness>,
        )

        await openRoleSelect(user)
        expect(screen.getByRole('option', { name: 'User' })).toBeInTheDocument()
        await user.click(screen.getByRole('option', { name: 'Admin' }))
        await user.click(screen.getByRole('button', { name: 'Go' }))

        expect(onSubmit).toHaveBeenCalledWith({ role: 'admin' }, expect.anything())
    })

    it('renders an empty option when emptyLabel is given', async () => {
        const user = userEvent.setup()
        render(
            <FormHarness onSubmit={onSubmit} defaultValues={{ role: '' }}>
                <FormSelectField
                    name="role"
                    label="Role"
                    options={ROLE_OPTIONS}
                    emptyLabel="Any"
                />
            </FormHarness>,
        )

        await openRoleSelect(user)

        expect(screen.getByRole('option', { name: 'Any' })).toBeInTheDocument()
        expect(screen.getAllByRole('option')).toHaveLength(3)
    })

    it('renders no empty option without emptyLabel', async () => {
        const user = userEvent.setup()
        render(
            <FormHarness onSubmit={onSubmit} defaultValues={{ role: '' }}>
                <FormSelectField name="role" label="Role" options={ROLE_OPTIONS} />
            </FormHarness>,
        )

        await openRoleSelect(user)

        expect(screen.queryByRole('option', { name: 'Any' })).not.toBeInTheDocument()
        expect(screen.getAllByRole('option')).toHaveLength(2)
    })

    it('disables the control', () => {
        render(
            <FormHarness onSubmit={onSubmit} defaultValues={{ role: 'user' }}>
                <FormSelectField
                    name="role"
                    label="Role"
                    options={ROLE_OPTIONS}
                    disabled
                />
            </FormHarness>,
        )

        expect(screen.getByRole('combobox', { name: /Role/ })).toHaveAttribute(
            'aria-disabled',
            'true',
        )
    })
})
