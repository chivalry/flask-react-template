/** @file The signed-in account's own page. */

import { Container, Typography } from '@mui/material'

import LinkedAccounts from '../components/account/LinkedAccounts'
import Passkeys from '../components/account/Passkeys'

/**
 * Render the account page: its sign-in providers and its passkeys.
 *
 * @returns The account page element.
 */
export default function Account() {
    return (
        <Container maxWidth="sm" sx={{ py: 4 }}>
            <Typography variant="h4" component="h1" gutterBottom>
                Account
            </Typography>
            <LinkedAccounts />
            <Passkeys />
        </Container>
    )
}
