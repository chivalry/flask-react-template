/** @file The label a deployment environment shows in the UI. */

/**
 * Name a non-production environment for the badge and the tab title.
 *
 * @param environment - The name `/api/health` reports, or undefined until it loads.
 * @returns The name in capitals, or null for production and while it is unknown.
 */
export function environmentLabel(environment: string | undefined): string | null {
    if (!environment || environment === 'production') return null
    return environment.toUpperCase()
}
