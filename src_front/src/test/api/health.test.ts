import type { AxiosResponse } from 'axios'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import client from '../../api/client'
import { getHealth } from '../../api/health'

vi.mock('../../api/client')

describe('health api', () => {
    beforeEach(() => {
        vi.resetAllMocks()
    })

    it('reads the unauthenticated health check', async () => {
        vi.mocked(client.get).mockResolvedValue({
            data: { status: 'ok', environment: 'staging' },
        } as AxiosResponse)

        const response = await getHealth()

        expect(client.get).toHaveBeenCalledWith('/health')
        expect(response.data.environment).toBe('staging')
    })
})
