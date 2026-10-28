/** @file Check local calendar dates and times, in the zone the global setup pins. */

import { expect, it } from 'vitest'

import {
    addLocalDays,
    formatLocalDate,
    formatLocalDateTime,
    localDayStartIso,
    localIsoDate,
    toDateTimeLocalValue,
} from '../../utils/dates'

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
// Daylight saving ends on 2026-11-01 in Los Angeles, so that day lasts 25 hours.
it.each([
    ['2026-10-31', 1, '2026-11-01'],
    ['2026-11-01', 1, '2026-11-02'],
    ['2026-10-27', -29, '2026-09-28'],
])('moves %s by %i days to %s', (isoDate, days, expected) => {
    expect(addLocalDays(isoDate, days)).toBe(expected)
})
it.each([
    ['2026-10-14', '2026-10-14T07:00:00.000Z'],
    ['2026-11-02', '2026-11-02T08:00:00.000Z'],
])('starts the local day %s at %s', (isoDate, expected) => {
    expect(localDayStartIso(isoDate)).toBe(expected)
})
it('formats a timestamp as a local date and time', () => {
    const timestamp = '2026-10-14T16:05:00Z'
    const formatted = formatLocalDateTime(timestamp)
    expect(formatted).toBe(
        new Date(timestamp).toLocaleString(undefined, {
            month: 'short',
            day: 'numeric',
            year: 'numeric',
            hour: 'numeric',
            minute: '2-digit',
        }),
    )
    expect(formatted).toContain('9:05')
})
