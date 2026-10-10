/** @file Landing page shown to signed-in users. */

import { Container, Typography } from '@mui/material'

/**
 * Render the placeholder landing page.
 *
 * @returns The home page element.
 */
export default function Home() {
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
