import { act, render, screen, waitFor } from '@testing-library/react'
import type { AxiosResponse } from 'axios'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { getHealth } from '../../../api/health'
import { APP_TITLE } from '../../../appTitle'
import EnvironmentBadge from '../../../components/layout/EnvironmentBadge'

vi.mock('../../../api/health')

const healthAnswers = (environment: string) =>
    vi.mocked(getHealth).mockResolvedValue({
        data: { status: 'ok', environment },
    } as AxiosResponse)

describe('EnvironmentBadge', () => {
    beforeEach(() => {
        vi.clearAllMocks()
        document.title = ''
    })

    it('marks a staging deployment with a badge and the tab title', async () => {
        healthAnswers('staging')

        render(<EnvironmentBadge />)

        expect(await screen.findByRole('status')).toHaveTextContent('STAGING')
        expect(screen.getByRole('status')).toHaveStyle({
            position: 'fixed',
            pointerEvents: 'none',
        })
        await waitFor(() => expect(document.title).toBe(`STAGING · ${APP_TITLE}`))
        expect(getHealth).toHaveBeenCalledTimes(1)
    })

    it('marks nothing in production', async () => {
        healthAnswers('production')

        render(<EnvironmentBadge />)
        await act(() => Promise.resolve())

        expect(getHealth).toHaveBeenCalledTimes(1)
        expect(screen.queryByRole('status')).not.toBeInTheDocument()
        expect(document.title).toBe(APP_TITLE)
    })

    it('marks nothing while the health check is pending', () => {
        vi.mocked(getHealth).mockReturnValue(new Promise(() => undefined))

        render(<EnvironmentBadge />)

        expect(screen.queryByRole('status')).not.toBeInTheDocument()
        expect(document.title).toBe(APP_TITLE)
    })

    it('marks nothing when the health check fails', async () => {
        vi.mocked(getHealth).mockRejectedValue(new Error('Network Error'))

        render(<EnvironmentBadge />)
        await act(() => Promise.resolve())

        expect(screen.queryByRole('status')).not.toBeInTheDocument()
        expect(document.title).toBe(APP_TITLE)
    })
})
