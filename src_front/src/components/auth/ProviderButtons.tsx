/** @file The "Continue with" buttons on the sign-in and registration pages. */

import { Button, Divider, Stack } from '@mui/material'

import { useProviders } from '../../hooks/useProviders'
import type { OAuthProviderInfo } from '../../types/auth'
import { startUrl } from '../../utils/oauth'

/** Props accepted by {@link ProviderLinks}. */
interface ProviderLinksProps {
    providers: OAuthProviderInfo[]
    next: string
}

/**
 * Render one "Continue with" link per provider.
 *
 * Each is a plain anchor, because the browser leaves the page for the provider.
 *
 * @param props - The component props.
 * @param props.providers - The enabled providers.
 * @param props.next - The path to return to after signing in.
 * @returns The links.
 */
export function ProviderLinks({ providers, next }: ProviderLinksProps) {
    return (
        <>
            {providers.map(({ name, label }) => (
                <Button
                    key={name}
                    variant="outlined"
                    fullWidth
                    href={startUrl(name, next)}
                >
                    Continue with {label}
                </Button>
            ))}
        </>
    )
}

/** Props accepted by {@link ProviderButtons}. */
interface ProviderButtonsProps {
    next: string
}

/**
 * Render one link per enabled provider, behind an "or" divider.
 *
 * With no provider enabled it renders nothing, divider included, so the page stays as
 * it was.
 *
 * @param props - The component props.
 * @param props.next - The path to return to after signing in.
 * @returns The buttons, or null.
 */
export default function ProviderButtons({ next }: ProviderButtonsProps) {
    const providers = useProviders()
    if (providers.length === 0) return null
    return (
        <Stack spacing={1} sx={{ mt: 2 }}>
            <Divider>or</Divider>
            <ProviderLinks providers={providers} next={next} />
        </Stack>
    )
}
