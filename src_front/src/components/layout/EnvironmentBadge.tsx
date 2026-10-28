/** @file Badge and tab title marking a non-production deployment, such as staging. */

import { Chip } from '@mui/material'
import { useEffect, useState } from 'react'

import { getHealth } from '../../api/health'
import { APP_TITLE } from '../../appTitle'
import { environmentLabel } from '../../utils/environment'

/**
 * Mark every page of a non-production deployment.
 *
 * A fixed badge names the environment and the tab title starts with it. Production,
 * and a health check that is still loading or has failed, render nothing, so
 * production is never mislabeled. The name is fetched once into local state rather
 * than a query: `useSessionQueryCache` clears every query when the account changes,
 * which would cancel the fetch during sign-in.
 *
 * @returns The badge, or null.
 */
export default function EnvironmentBadge() {
    const [environment, setEnvironment] = useState<string>()
    const label = environmentLabel(environment)

    useEffect(() => {
        void getHealth()
            .then((response) => setEnvironment(response.data.environment))
            .catch(() => undefined)
    }, [])

    useEffect(() => {
        document.title = label ? `${label} · ${APP_TITLE}` : APP_TITLE
    }, [label])

    if (!label) return null
    return (
        <Chip
            role="status"
            label={label}
            color="warning"
            sx={{
                position: 'fixed',
                left: 12,
                bottom: 12,
                zIndex: 'tooltip',
                fontWeight: 700,
                pointerEvents: 'none',
            }}
        />
    )
}
