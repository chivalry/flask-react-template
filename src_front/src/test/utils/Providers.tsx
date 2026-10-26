/** @file The query client and memory router that tests render screens inside. */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useState } from 'react'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router-dom'

/**
 * Wrap children in a fresh, non-retrying query client and a memory router.
 *
 * The client is created once per mount, so a re-render keeps its cache instead of
 * dropping every query and fetching it again.
 */
export default function Providers({
    children,
    route = '/',
}: {
    children: ReactNode
    route?: string
}) {
    const [client] = useState(
        () =>
            new QueryClient({
                defaultOptions: {
                    queries: { retry: false, gcTime: 0 },
                    mutations: { retry: false },
                },
            }),
    )
    return (
        <QueryClientProvider client={client}>
            <MemoryRouter initialEntries={[route]}>{children}</MemoryRouter>
        </QueryClientProvider>
    )
}
