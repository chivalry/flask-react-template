/** @file Form context shared by controlled-field tests. */
import type { ReactNode } from 'react'
import { FormProvider, useForm } from 'react-hook-form'
import type { FieldValues } from 'react-hook-form'

/** Form harness properties. */
interface FormHarnessProps {
    defaultValues?: FieldValues
    children: ReactNode
    onSubmit: (values: FieldValues, event?: unknown) => void
}

/** Render fields inside a working form. */
export default function FormHarness(props: FormHarnessProps) {
    const { defaultValues, children, onSubmit } = props
    const methods = useForm<FieldValues>({ defaultValues })
    return (
        <FormProvider {...methods}>
            <form onSubmit={methods.handleSubmit(onSubmit)} noValidate>
                {children}
                <button type="submit">Go</button>
            </form>
        </FormProvider>
    )
}
