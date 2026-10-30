/** @file Record counts as list headings show and announce them. */

/** The nouns a count reads with: `one` for exactly one record, `other` otherwise. */
export interface CountNouns {
    one: string
    other: string
}

/** US thousands separators, fixed so the output does not depend on the machine. */
const COUNT_FORMAT = new Intl.NumberFormat('en-US')

/**
 * Format a count with thousands separators.
 *
 * @param count - The number of records.
 * @returns The count as text, such as `1,234`.
 */
export function formatCount(count: number): string {
    return COUNT_FORMAT.format(count)
}

/**
 * Choose the noun that agrees with a count.
 *
 * @param count - The number of records.
 * @param nouns - The singular and plural nouns.
 * @returns The singular noun for exactly one record, otherwise the plural.
 */
export function chooseCountNoun(count: number, nouns: CountNouns): string {
    return count === 1 ? nouns.one : nouns.other
}
