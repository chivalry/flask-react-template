/** @file Landing page: the accounts for an admin, a welcome for everyone else. */

import { Container, Typography } from '@mui/material'

import UsersMasterDetail from '../components/admin/UsersMasterDetail'
import { useAuthStore } from '../store/auth'
import { isAdmin } from '../types/auth'

/**
 * Render the placeholder welcome.
 *
 * @returns The welcome element.
 */
function Welcome() {
    return (
        <Container maxWidth="sm" sx={{ py: 8, textAlign: 'center' }}>
            <Typography variant="h3" component="h1" gutterBottom>
                Hello, World
            </Typography>
            <Typography color="text.secondary">
                Your Flask + React project starts here. Edit{' '}
                <code>src_front/src/pages/Home.tsx</code> to get going.
            </Typography>
        </Container>
    )
}

/**
 * Render the landing page.
 *
 * An admin sees the accounts as a master-detail page, the layout kit's example. The
 * accounts routes are admin-only, so everyone else sees the welcome. A project
 * replaces both with its own landing page.
 *
 * @returns The home page element.
 */
export default function Home() {
    const showAccounts = useAuthStore((s) => s.user !== null && isAdmin(s.user.role))
    return showAccounts ? <UsersMasterDetail /> : <Welcome />
}
