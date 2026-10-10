/** @file Account registration page. */

import { zodResolver } from '@hookform/resolvers/zod'
import { useForm } from 'react-hook-form'
import type { FieldErrors, UseFormRegister } from 'react-hook-form'
import { Link } from 'react-router-dom'
import { z } from 'zod'

import { login, register as registerUser } from '../api/auth'
import AuthFormLayout, { AuthTextField } from '../components/AuthFormLayout'
import { useAuthFormState } from '../hooks/useAuthFormState'

const schema = z
    .object({
        email: z.string().email('Enter a valid email.'),
        password: z.string().min(8, 'Password must be at least 8 characters.'),
        confirmPassword: z.string(),
    })
    .refine((d) => d.password === d.confirmPassword, {
        message: 'Passwords do not match.',
        path: ['confirmPassword'],
    })

/** The registration form's validated values. */
type FormData = z.infer<typeof schema>

/** Props accepted by {@link RegisterFields}. */
interface RegisterFieldsProps {
    register: UseFormRegister<FormData>
    errors: FieldErrors<FormData>
}

/**
 * Render the registration form's three credential fields.
 *
 * @param props - The component props.
 * @param props.register - The form's field registrar.
 * @param props.errors - The form's current validation errors.
 * @returns The credential fields.
 */
function RegisterFields({ register, errors }: RegisterFieldsProps) {
    return (
        <>
            <AuthTextField
                registration={register('email')}
                label="Email"
                type="email"
                error={errors.email?.message}
            />
            <AuthTextField
                registration={register('password')}
                label="Password"
                type="password"
                error={errors.password?.message}
            />
            <AuthTextField
                registration={register('confirmPassword')}
                label="Confirm password"
                type="password"
                error={errors.confirmPassword?.message}
            />
        </>
    )
}

/**
 * Render the registration form and create the account on submit.
 *
 * @returns The registration page element.
 */
export default function Register() {
    const { apiError, handleAuthAction } = useAuthFormState()

    const {
        register,
        handleSubmit,
        formState: { errors, isSubmitting },
    } = useForm<FormData>({ resolver: zodResolver(schema) })

    /**
     * Register the account, then sign in with the same credentials.
     *
     * The explicit login is what establishes the session cookie this client
     * relies on, rather than depending on the register response to do it.
     *
     * @param data - The validated form values.
     * @returns A promise that settles when registration completes.
     */
    const onSubmit = (data: FormData) =>
        handleAuthAction(async () => {
            await registerUser(data.email, data.password)
            await login(data.email, data.password)
        }, 'Registration failed.')

    return (
        <AuthFormLayout
            title="Create account"
            apiError={apiError}
            isSubmitting={isSubmitting}
            submitLabel={isSubmitting ? 'Creating account…' : 'Create account'}
            footer={
                <>
                    Already have an account? <Link to="/login">Sign in</Link>
                </>
            }
            onSubmit={handleSubmit(onSubmit)}
        >
            <RegisterFields register={register} errors={errors} />
        </AuthFormLayout>
    )
}
