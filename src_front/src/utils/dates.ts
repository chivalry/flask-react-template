/** @file Calendar dates and local times, without the UTC traps of `Date` parsing. */

/**
 * Pad a number to two digits.
 *
 * @param value - The number.
 * @returns For example `07`.
 */
const pad = (value: number) => String(value).padStart(2, '0')

/**
 * Build a `YYYY-MM-DD` string from a date's local calendar day.
 *
 * @param date - The moment.
 * @returns The local date; `toISOString()` would give the UTC one.
 */
export function localIsoDate(date: Date): string {
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}

/**
 * Parse a `YYYY-MM-DD` string as a local calendar day.
 *
 * @param isoDate - The date.
 * @returns Local midnight of that day; `new Date(isoDate)` would be UTC midnight.
 */
function parseLocalDate(isoDate: string): Date {
    const [year, month, day] = isoDate.split('-').map(Number) as [number, number, number]
    return new Date(year, month - 1, day)
}

/**
 * Format a `YYYY-MM-DD` string for display.
 *
 * @param isoDate - The date.
 * @returns For example `Oct 14, 2026`.
 */
export function formatLocalDate(isoDate: string): string {
    return parseLocalDate(isoDate).toLocaleDateString(undefined, {
        month: 'short',
        day: 'numeric',
        year: 'numeric',
    })
}

/**
 * Move a `YYYY-MM-DD` date by whole days.
 *
 * The move counts calendar days, not 24-hour spans, so daylight-saving changes do not
 * shift the day.
 *
 * @param isoDate - The date.
 * @param days - How many days to add; negative moves back.
 * @returns The moved date, for example `2026-11-02` from `2026-11-01` and `1`.
 */
export function addLocalDays(isoDate: string, days: number): string {
    const date = parseLocalDate(isoDate)
    date.setDate(date.getDate() + days)
    return localIsoDate(date)
}

/**
 * Name the moment a local calendar day starts, in the form the API reads moments.
 *
 * @param isoDate - The day, as `YYYY-MM-DD`.
 * @returns Local midnight of that day in ISO 8601 UTC, for example
 *   `2026-10-14T07:00:00.000Z` in California.
 */
export function localDayStartIso(isoDate: string): string {
    return parseLocalDate(isoDate).toISOString()
}

/**
 * Format an ISO 8601 timestamp in local time.
 *
 * @param timestamp - The moment, such as `2026-10-14T16:05:00Z`.
 * @returns For example `Oct 14, 2026, 9:05 AM`.
 */
export function formatLocalDateTime(timestamp: string): string {
    return new Date(timestamp).toLocaleString(undefined, {
        month: 'short',
        day: 'numeric',
        year: 'numeric',
        hour: 'numeric',
        minute: '2-digit',
    })
}

/**
 * Build a `datetime-local` input value from a date's local time.
 *
 * @param date - The moment.
 * @returns For example `2026-10-12T09:30`.
 */
export function toDateTimeLocalValue(date: Date): string {
    return `${localIsoDate(date)}T${pad(date.getHours())}:${pad(date.getMinutes())}`
}
