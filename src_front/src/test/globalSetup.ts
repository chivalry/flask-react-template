/** @file Run every test west of UTC, where date-only bugs show. */

/**
 * Pin the time zone before the workers start, so they inherit it.
 *
 * `new Date('2026-10-14')` is UTC midnight, which is October 13 in Los Angeles. In
 * UTC that bug would pass unnoticed.
 */
export function setup() {
    process.env.TZ = 'America/Los_Angeles'
}
