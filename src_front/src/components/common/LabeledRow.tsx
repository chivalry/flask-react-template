/** @file A caption beside a wrapping row of chips on a detail pane. */

import { Stack, Typography } from '@mui/material'
import type { ReactNode } from 'react'

/** Props accepted by {@link LabeledRow}. */
interface LabeledRowProps {
    label: string
    children: ReactNode
}

/**
 * Render a caption beside a row of chips, or beside a note when there are none.
 *
 * @param props - The component props.
 * @returns The row element.
 */
export default function LabeledRow(props: LabeledRowProps) {
    const { label, children } = props
    return (
        <Stack direction="row" alignItems="center" flexWrap="wrap" gap={0.5}>
            <Typography variant="caption" color="text.secondary" sx={{ mr: 0.5 }}>
                {label}
            </Typography>
            {children}
        </Stack>
    )
}
