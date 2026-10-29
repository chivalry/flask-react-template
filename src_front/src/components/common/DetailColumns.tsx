/** @file A detail pane's sections in two columns that stack on narrow screens. */

import { Stack } from '@mui/material'
import type { SxProps, Theme } from '@mui/material'
import type { ReactNode } from 'react'

/** Props accepted by {@link DetailColumns}. */
interface DetailColumnsProps {
    left: ReactNode
    right: ReactNode
}

/**
 * Split the row evenly from `lg` up, and break a long word such as a URL inside its
 * column instead of letting it spill into the other one.
 */
const COLUMN_SX: SxProps<Theme> = {
    flex: { lg: 1 },
    minWidth: 0,
    overflowWrap: 'break-word',
}

/**
 * Render the left and right sections side by side from the `lg` breakpoint up; below
 * it, stack them with the left column first.
 *
 * @param props - The component props.
 * @returns The columns element.
 */
export default function DetailColumns(props: DetailColumnsProps) {
    const { left, right } = props
    return (
        <Stack direction={{ xs: 'column', lg: 'row' }} spacing={3}>
            <Stack spacing={3} sx={COLUMN_SX}>
                {left}
            </Stack>
            <Stack spacing={3} sx={COLUMN_SX}>
                {right}
            </Stack>
        </Stack>
    )
}
