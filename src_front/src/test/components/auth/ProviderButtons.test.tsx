/** @file One "Continue with" link per enabled provider, and nothing without one. */

import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { listProviders } from '../../../api/oauth'
import ProviderButtons from '../../../components/auth/ProviderButtons'
import { googleProvider } from '../../utils/fixtures'

vi.mock('../../../api/oauth')

describe('ProviderButtons', () => {
    beforeEach(() => {
        vi.clearAllMocks()
    })

    it('links each provider to its start route, carrying the encoded next', async () => {
        vi.mocked(listProviders).mockResolvedValue([googleProvider])

        render(<ProviderButtons next="/widgets/12?tab=notes" />)

        expect(
            await screen.findByRole('link', { name: 'Continue with Google' }),
        ).toHaveAttribute(
            'href',
            '/api/v1/auth/oauth/google/start?next=%2Fwidgets%2F12%3Ftab%3Dnotes',
        )
        expect(screen.getByRole('separator')).toHaveTextContent('or')
    })

    it('renders no link and no divider when no provider is enabled', async () => {
        vi.mocked(listProviders).mockResolvedValue([])

        render(<ProviderButtons next="/" />)

        await waitFor(() => expect(listProviders).toHaveBeenCalledTimes(1))
        expect(screen.queryByRole('link')).not.toBeInTheDocument()
        expect(screen.queryByRole('separator')).not.toBeInTheDocument()
    })
})
