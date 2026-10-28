/** @file The unauthenticated health check, which names the deployment environment. */

import client from './client'

/** The body the health endpoint returns. */
interface HealthResponse {
    status: string
    environment: string
}

/**
 * Ask the backend whether it is serving, and which environment it belongs to.
 *
 * @returns The response wrapping the health body.
 */
export const getHealth = () => client.get<HealthResponse>('/health')
