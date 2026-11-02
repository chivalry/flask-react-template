/** @file The signed-in account's own page. */

import { Container, Typography } from '@mui/material'

import LinkedAccounts from '../components/account/LinkedAccounts'

/**
 * Render the account page, which later sections, such as passkeys, join.
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
        </Container>
    )
}
