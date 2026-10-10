import { describe, expect, it } from 'vitest'

import { theme } from '../theme'

describe('theme', () => {
    it('uses the light palette', () => {
        expect(theme.palette.mode).toBe('light')
    })
})
