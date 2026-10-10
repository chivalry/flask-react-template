/** @file Sign-in page. */

import { zodResolver } from '@hookform/resolvers/zod'
import { useForm } from 'react-hook-form'
import { Link } from 'react-router-dom'
import { z } from 'zod'

import { login } from '../api/auth'
import AuthFormLayout, { AuthTextField } from '../components/AuthFormLayout'
import { useAuthFormState } from '../hooks/useAuthFormState'

const schema = z.object({
    email: z.string().email('Enter a valid email.'),
    password: z.string().min(1, 'Password is required.'),
})

/** The sign-in form's validated values. */
type FormData = z.infer<typeof schema>

/**
 * Render the sign-in form and submit it to the auth API.
 *
 * Validates only that a password was entered, not its length, so an account
 * created before a policy change can still sign in.
 *
 * @returns The sign-in page element.
 */
export default function Login() {
    const { apiError, handleAuthAction } = useAuthFormState()

    const {
        register,
        handleSubmit,
        formState: { errors, isSubmitting },
    } = useForm<FormData>({ resolver: zodResolver(schema) })

    /**
     * Sign in with the submitted credentials.
     *
     * @param data - The validated form values.
     * @returns A promise that settles when the sign-in attempt completes.
     */
    const onSubmit = (data: FormData) =>
        handleAuthAction(() => login(data.email, data.password), 'Login failed.')

    return (
        <AuthFormLayout
            title="Sign in"
            apiError={apiError}
            isSubmitting={isSubmitting}
            submitLabel={isSubmitting ? 'Signing in…' : 'Sign in'}
            footer={
                <>
                    No account? <Link to="/register">Register</Link>
                </>
            }
            onSubmit={handleSubmit(onSubmit)}
        >
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
        </AuthFormLayout>
    )
}
