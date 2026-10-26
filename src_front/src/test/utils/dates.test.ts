/** @file Check local calendar dates and times, in the zone the global setup pins. */

import { expect, it } from 'vitest'

import { formatLocalDate, localIsoDate, toDateTimeLocalValue } from '../../utils/dates'

it('runs west of UTC, where an ISO date parses to the day before', () => {
    expect(new Date('2026-10-14').getDate()).toBe(13)
})
it('builds the local calendar date, not the UTC one', () => {
    expect(localIsoDate(new Date(2026, 0, 5, 23, 30))).toBe('2026-01-05')
})
it('formats a date-only string as that local day', () => {
    expect(formatLocalDate('2026-10-14')).toBe(
        new Date(2026, 9, 14).toLocaleDateString(undefined, {
            month: 'short',
            day: 'numeric',
            year: 'numeric',
        }),
    )
})
it('builds a datetime-local value that round-trips to the same moment', () => {
    const moment = new Date(2026, 9, 12, 9, 5)
    const value = toDateTimeLocalValue(moment)
    expect(value).toBe('2026-10-12T09:05')
    expect(new Date(value).getTime()).toBe(moment.getTime())
})
