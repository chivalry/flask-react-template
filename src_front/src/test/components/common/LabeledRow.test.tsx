/** @file LabeledRow shows its caption in front of the chips it is given. */

import { Chip } from '@mui/material'
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import LabeledRow from '../../../components/common/LabeledRow'

describe('LabeledRow', () => {
    it('shows the caption and then each chip, in one row', () => {
        render(
            <LabeledRow label="Tags">
                <Chip label="Buyer" />
                <Chip label="Cash" />
            </LabeledRow>,
        )

        expect(screen.getByText('Tags').parentElement).toHaveTextContent('TagsBuyerCash')
    })
})
