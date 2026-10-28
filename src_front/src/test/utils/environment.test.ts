import { describe, expect, it } from 'vitest'

import { environmentLabel } from '../../utils/environment'

describe('environmentLabel', () => {
    it('labels a non-production environment in capitals', () => {
        expect(environmentLabel('staging')).toBe('STAGING')
        expect(environmentLabel('qa')).toBe('QA')
    })

    it('labels neither production nor an environment that has not loaded', () => {
        expect(environmentLabel('production')).toBeNull()
        expect(environmentLabel(undefined)).toBeNull()
        expect(environmentLabel('')).toBeNull()
    })
})
