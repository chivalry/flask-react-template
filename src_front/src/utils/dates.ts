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
 * Build a `datetime-local` input value from a date's local time.
 *
 * @param date - The moment.
 * @returns For example `2026-10-12T09:30`.
 */
export function toDateTimeLocalValue(date: Date): string {
    return `${localIsoDate(date)}T${pad(date.getHours())}:${pad(date.getMinutes())}`
}
