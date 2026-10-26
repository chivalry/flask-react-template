import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import FormSwitchField from '../../../components/common/FormSwitchField'
import FormHarness from '../../utils/FormHarness'

const onSubmit = vi.fn()

describe('FormSwitchField', () => {
    beforeEach(() => {
        vi.clearAllMocks()
    })

    it('reflects the boolean held in the form', () => {
        render(
            <FormHarness onSubmit={onSubmit} defaultValues={{ is_active: true }}>
                <FormSwitchField name="is_active" label="Active" />
            </FormHarness>,
        )

        expect(screen.getByRole('checkbox', { name: 'Active' })).toBeChecked()
    })

    it('is off when the form holds no value', () => {
        render(
            <FormHarness onSubmit={onSubmit}>
                <FormSwitchField name="is_active" label="Active" />
            </FormHarness>,
        )

        expect(screen.getByRole('checkbox', { name: 'Active' })).not.toBeChecked()
    })

    it('writes the toggled value back to the form', async () => {
        const user = userEvent.setup()
        render(
            <FormHarness onSubmit={onSubmit} defaultValues={{ is_active: true }}>
                <FormSwitchField name="is_active" label="Active" />
            </FormHarness>,
        )

        await user.click(screen.getByRole('checkbox', { name: 'Active' }))
        expect(screen.getByRole('checkbox', { name: 'Active' })).not.toBeChecked()
        await user.click(screen.getByRole('button', { name: 'Go' }))

        expect(onSubmit).toHaveBeenCalledWith({ is_active: false }, expect.anything())
    })

    it('disables the switch', () => {
        render(
            <FormHarness onSubmit={onSubmit} defaultValues={{ is_active: true }}>
                <FormSwitchField name="is_active" label="Active" disabled />
            </FormHarness>,
        )

        expect(screen.getByRole('checkbox', { name: 'Active' })).toBeDisabled()
    })
})
