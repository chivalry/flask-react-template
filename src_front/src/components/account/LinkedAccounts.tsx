/** @file The Account page's section for linking and unlinking sign-in providers. */

import {
    Alert,
    Box,
    Button,
    List,
    ListItem,
    ListItemText,
    Stack,
    Typography,
} from '@mui/material'
import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'

import { useLinkedAccounts, useUnlinkAccount } from '../../hooks/oauth'
import { useProviders } from '../../hooks/useProviders'
import type { LinkedAccount, OAuthProviderInfo } from '../../types/auth'
import { linkUrl, oauthErrorMessage } from '../../utils/oauth'
import ConfirmDialog from '../common/ConfirmDialog'
import QueryState from '../common/QueryState'

/** Props accepted by {@link LinkedProviders}. */
interface LinkedProvidersProps {
    linked: LinkedAccount[]
    providers: OAuthProviderInfo[]
    labelFor: (provider: string) => string
    onUnlink: (account: LinkedAccount) => void
}

/**
 * Render the account's links, then a link button for each provider it lacks.
 *
 * @param props - The component props.
 * @returns The list and the buttons.
 */
function LinkedProviders(props: LinkedProvidersProps) {
    const { linked, providers, labelFor, onUnlink } = props
    const unlinked = providers.filter(
        ({ name }) => !linked.some(({ provider }) => provider === name),
    )
    return (
        <>
            {linked.length === 0 && (
                <Typography color="text.secondary">No providers are linked.</Typography>
            )}
            <List disablePadding>
                {linked.map((account) => (
                    <ListItem
                        key={account.provider}
                        divider
                        secondaryAction={
                            <Button
                                aria-label={`Unlink ${labelFor(account.provider)}`}
                                onClick={() => onUnlink(account)}
                            >
                                Unlink
                            </Button>
                        }
                    >
                        <ListItemText
                            primary={labelFor(account.provider)}
                            secondary={account.email}
                        />
                    </ListItem>
                ))}
            </List>
            <Stack direction="row" spacing={1} sx={{ mt: 2, flexWrap: 'wrap' }}>
                {unlinked.map(({ name, label }) => (
                    <Button key={name} variant="outlined" href={linkUrl(name)}>
                        Link {label}
                    </Button>
                ))}
            </Stack>
        </>
    )
}

/** Props accepted by {@link UnlinkDialog}. */
interface UnlinkDialogProps {
    account: LinkedAccount | null
    labelFor: (provider: string) => string
    onClose: () => void
}

/**
 * Confirm removing a link; a refusal stays open and shows the server's message.
 *
 * @param props - The component props.
 * @returns The confirmation, open while an account is chosen.
 */
function UnlinkDialog(props: UnlinkDialogProps) {
    const { account, labelFor, onClose } = props
    const unlink = useUnlinkAccount()
    // In production builds the React Compiler compares the paths confirm reads while
    // rendering, when account is still null, so the provider is read safely here.
    const provider = account?.provider

    /** Remove the chosen link, then close the confirmation. */
    const confirm = async () => {
        // Unlink is clickable only while open, and it is open only with an account.
        await unlink.mutateAsync(provider!)
        onClose()
    }

    return (
        <ConfirmDialog
            open={account !== null}
            title="Unlink provider"
            message={account ? `Stop using ${labelFor(account.provider)}?` : ''}
            confirmLabel="Unlink"
            onCancel={onClose}
            onConfirm={confirm}
        />
    )
}

/**
 * Show the providers the account can sign in with, and let it link and unlink them.
 *
 * A failed link returns here with `?error=`, shown above the list. A link to a provider
 * since disabled shows its name.
 *
 * @returns The section element.
 */
export default function LinkedAccounts() {
    const accounts = useLinkedAccounts()
    const providers = useProviders()
    const [params] = useSearchParams()
    const [unlinking, setUnlinking] = useState<LinkedAccount | null>(null)
    const linkError = oauthErrorMessage(params.get('error'))

    /**
     * Name a provider for the viewer.
     *
     * @param provider - The provider's name.
     * @returns Its label, or the name when it is no longer enabled.
     */
    const labelFor = (provider: string) =>
        providers.find(({ name }) => name === provider)?.label ?? provider

    return (
        <Box component="section">
            <Typography variant="h6" component="h2" gutterBottom>
                Sign-in providers
            </Typography>
            {linkError && (
                <Alert severity="error" sx={{ mb: 2 }}>
                    {linkError}
                </Alert>
            )}
            <QueryState query={accounts}>
                {(linked) => (
                    <LinkedProviders
                        linked={linked}
                        providers={providers}
                        labelFor={labelFor}
                        onUnlink={setUnlinking}
                    />
                )}
            </QueryState>
            <UnlinkDialog
                account={unlinking}
                labelFor={labelFor}
                onClose={() => setUnlinking(null)}
            />
        </Box>
    )
}
