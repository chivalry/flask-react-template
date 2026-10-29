/** @file Count formatting and noun agreement for list headings. */

import { describe, expect, it } from 'vitest'

import { chooseCountNoun, formatCount } from '../../utils/counts'

describe('formatCount', () => {
    it('groups thousands with commas', () => {
        expect(formatCount(0)).toBe('0')
        expect(formatCount(1234)).toBe('1,234')
        expect(formatCount(1234567)).toBe('1,234,567')
    })
})

describe('chooseCountNoun', () => {
    it.each([
        [0, 'people'],
        [1, 'person'],
        [2, 'people'],
    ])('reads %i with %s', (count, noun) => {
        expect(chooseCountNoun(count, { one: 'person', other: 'people' })).toBe(noun)
    })
})
