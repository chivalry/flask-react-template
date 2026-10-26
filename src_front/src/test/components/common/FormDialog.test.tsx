import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { z } from 'zod'

import FormDialog from '../../../components/common/FormDialog'
import type { FormDialogProps } from '../../../components/common/FormDialog'
import FormTextField from '../../../components/common/FormTextField'

const schema = z.object({
    name: z.string().trim().min(1, 'Enter a name.'),
})

type FormValues = z.infer<typeof schema>

type DialogOverrides = Partial<FormDialogProps<FormValues, FormValues>>

const onClose = vi.fn()
const onSubmit = vi.fn<(values: FormValues) => Promise<void>>()

/** Build the dialog under test, with one Name field. */
const buildDialogElement = (overrides: DialogOverrides = {}) => (
    <FormDialog
        open
        title="New record"
        schema={schema}
        defaultValues={{ name: '' }}
        onClose={onClose}
        onSubmit={onSubmit}
        {...overrides}
    >
        <FormTextField name="name" label="Name" />
    </FormDialog>
)

const renderDialog = (overrides: DialogOverrides = {}) =>
    render(buildDialogElement(overrides))

/** Type a name into the field and press Save. */
const submitName = async (user: ReturnType<typeof userEvent.setup>, name: string) => {
    await user.type(screen.getByLabelText('Name'), name)
    await user.click(screen.getByRole('button', { name: 'Save' }))
}

describe('FormDialog', () => {
    beforeEach(() => {
        vi.clearAllMocks()
        onSubmit.mockResolvedValue(undefined)
    })

    it('renders the title, the fields, and the default Save label', () => {
        renderDialog()

        const dialog = screen.getByRole('dialog')
        expect(within(dialog).getByText('New record')).toBeInTheDocument()
        expect(within(dialog).getByLabelText('Name')).toHaveValue('')
        expect(within(dialog).getByRole('button', { name: 'Save' })).toBeInTheDocument()
        expect(within(dialog).getByRole('button', { name: 'Cancel' })).toBeInTheDocument()
    })

    it('shows a custom submit label', () => {
        renderDialog({ submitLabel: 'Create' })

        expect(screen.getByRole('button', { name: 'Create' })).toBeInTheDocument()
        expect(screen.queryByRole('button', { name: 'Save' })).not.toBeInTheDocument()
    })

    it('submits the values parsed by the schema', async () => {
        const user = userEvent.setup()
        renderDialog()

        await submitName(user, '  Ada  ')

        await waitFor(() => expect(onSubmit).toHaveBeenCalledWith({ name: 'Ada' }))
        expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    })

    it('shows the schema message through the field and does not submit', async () => {
        const user = userEvent.setup()
        renderDialog()

        await user.click(screen.getByRole('button', { name: 'Save' }))

        expect(await screen.findByText('Enter a name.')).toBeInTheDocument()
        expect(onSubmit).not.toHaveBeenCalled()
    })

    it('shows the failure message and stays open when onSubmit rejects', async () => {
        const user = userEvent.setup()
        onSubmit.mockRejectedValue(new Error('That name is taken.'))
        renderDialog()

        await submitName(user, 'Ada')

        expect(await screen.findByRole('alert')).toHaveTextContent('That name is taken.')
        expect(screen.getByRole('dialog')).toBeInTheDocument()
        expect(onClose).not.toHaveBeenCalled()
    })

    it('calls onClose when Cancel is clicked', async () => {
        const user = userEvent.setup()
        renderDialog()

        await user.click(screen.getByRole('button', { name: 'Cancel' }))

        expect(onClose).toHaveBeenCalledTimes(1)
    })

    it('disables the submit button while onSubmit is pending', async () => {
        const user = userEvent.setup()
        let resolveSubmit: () => void = () => undefined
        onSubmit.mockReturnValue(
            new Promise<void>((resolve) => {
                resolveSubmit = resolve
            }),
        )
        renderDialog()

        await submitName(user, 'Ada')

        await waitFor(() =>
            expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled(),
        )

        resolveSubmit()

        await waitFor(() =>
            expect(screen.getByRole('button', { name: 'Save' })).toBeEnabled(),
        )
    })

    it('disables the submit button as soon as the dialog starts closing', () => {
        const { rerender } = renderDialog()
        expect(screen.getByRole('button', { name: 'Save' })).toBeEnabled()

        rerender(buildDialogElement({ open: false }))

        // MUI keeps the content mounted through its fade-out. A second Save there
        // would reach the caller's submit after it had cleared its editing state.
        expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled()
    })

    it('renders nothing while closed', () => {
        renderDialog({ open: false })

        expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    })
})
