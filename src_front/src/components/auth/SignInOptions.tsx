/** @file The other ways to sign in, beneath the sign-in form: a passkey and providers. */

import { Button, Divider, Stack } from '@mui/material'

import { usePasskeyLogin, type RunAuthAction } from '../../hooks/usePasskeyLogin'
import { useProviders } from '../../hooks/useProviders'
import { ProviderLinks } from './ProviderButtons'

/** Props accepted by {@link SignInOptions}. */
interface SignInOptionsProps {
    next: string
    run: RunAuthAction
}

/**
 * Render a passkey button and one link per enabled provider, behind an "or" divider.
 *
 * The button shows wherever the browser supports passkeys, and the email field's
 * autofill offers them too. With neither a passkey nor a provider to offer, it renders
 * nothing, divider included.
 *
 * @param props - The component props.
 * @param props.next - The path a provider sign-in returns to.
 * @param props.run - The page's `handleAuthAction`, which a passkey sign-in goes through.
 * @returns The options, or null.
 */
export default function SignInOptions({ next, run }: SignInOptionsProps) {
    const providers = useProviders()
    const passkey = usePasskeyLogin(run)
    if (providers.length === 0 && !passkey.available) return null
    return (
        <Stack spacing={1} sx={{ mt: 2 }}>
            <Divider>or</Divider>
            {passkey.available && (
                <Button
                    variant="outlined"
                    fullWidth
                    disabled={passkey.pending}
                    onClick={() => void passkey.signIn()}
                >
                    Sign in with a passkey
                </Button>
            )}
            <ProviderLinks providers={providers} next={next} />
        </Stack>
    )
}
