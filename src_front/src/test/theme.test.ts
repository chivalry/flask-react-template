import { describe, expect, it } from 'vitest'

import { theme } from '../theme'

describe('theme', () => {
    it('uses the light palette', () => {
        expect(theme.palette.mode).toBe('light')
    })

    it('keeps input text at 16px below the sm breakpoint', () => {
        expect(theme.components?.MuiInputBase?.styleOverrides?.input).toEqual({
            [theme.breakpoints.down('sm')]: { fontSize: 16 },
        })
    })
})
