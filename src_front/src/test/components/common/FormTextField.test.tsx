import { zodResolver } from '@hookform/resolvers/zod'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { FormProvider, useForm } from 'react-hook-form'
import type { FieldValues } from 'react-hook-form'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { z } from 'zod'
import type { ZodType } from 'zod'

import FormTextField from '../../../components/common/FormTextField'

const schema = z.object({
    name: z.string().min(1, 'Enter a name.'),
})

const onSubmit = vi.fn()

/** Props accepted by the form harness. */
interface HarnessProps {
    defaultValues?: FieldValues
    schema?: ZodType<FieldValues, FieldValues>
    children: ReactNode
}

/** Mount the field inside a real form so it reads and writes form state. */
function Harness(props: HarnessProps) {
    const { defaultValues, schema: formSchema, children } = props
    const methods = useForm<FieldValues>({
        defaultValues,
        resolver: formSchema ? zodResolver(formSchema) : undefined,
    })
    return (
        <FormProvider {...methods}>
            <form onSubmit={methods.handleSubmit(onSubmit)} noValidate>
                {children}
                <button type="submit">Go</button>
            </form>
        </FormProvider>
    )
}

describe('FormTextField', () => {
    beforeEach(() => {
        vi.clearAllMocks()
    })

    it('shows the value held in the form', () => {
        render(
            <Harness defaultValues={{ name: 'Ada' }}>
                <FormTextField name="name" label="Name" />
            </Harness>,
        )

        expect(screen.getByLabelText('Name')).toHaveValue('Ada')
    })

    it('writes typed text back to the form', async () => {
        const user = userEvent.setup()
        render(
            <Harness defaultValues={{ name: 'Ada' }}>
                <FormTextField name="name" label="Name" />
            </Harness>,
        )

        await user.type(screen.getByLabelText('Name'), ' Lovelace')
        await user.click(screen.getByRole('button', { name: 'Go' }))

        expect(onSubmit).toHaveBeenCalledWith({ name: 'Ada Lovelace' }, expect.anything())
    })

    it('shows the helper text while the value is valid', () => {
        render(
            <Harness defaultValues={{ name: 'Ada' }} schema={schema}>
                <FormTextField name="name" label="Name" helperText="Who they are." />
            </Harness>,
        )

        expect(screen.getByText('Who they are.')).toBeInTheDocument()
        expect(screen.getByLabelText('Name')).toHaveAttribute('aria-invalid', 'false')
    })

    it('replaces the helper text with the validation message', async () => {
        const user = userEvent.setup()
        render(
            <Harness defaultValues={{ name: '' }} schema={schema}>
                <FormTextField name="name" label="Name" helperText="Who they are." />
            </Harness>,
        )

        await user.click(screen.getByRole('button', { name: 'Go' }))

        expect(await screen.findByText('Enter a name.')).toBeInTheDocument()
        expect(screen.queryByText('Who they are.')).not.toBeInTheDocument()
        expect(screen.getByLabelText('Name')).toHaveAttribute('aria-invalid', 'true')
        expect(onSubmit).not.toHaveBeenCalled()
    })

    it('shows an empty string when the form holds no value', () => {
        render(
            <Harness>
                <FormTextField name="name" label="Name" />
            </Harness>,
        )

        expect(screen.getByLabelText('Name')).toHaveValue('')
    })
})
