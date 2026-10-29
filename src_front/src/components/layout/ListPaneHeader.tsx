/** @file A list pane's heading with its record count and an action, such as New. */

import { Box, Stack, Typography } from '@mui/material'
import type { ReactNode } from 'react'

import { chooseCountNoun, formatCount } from '../../utils/counts'
import type { CountNouns } from '../../utils/counts'

/**
 * Hides text on screen and keeps it for screen readers. The values are MUI's
 * `visuallyHidden`; `@mui/utils` is only a transitive dependency, and fallow fails an
 * import of an unlisted one.
 */
const VISUALLY_HIDDEN = {
    border: 0,
    clip: 'rect(0 0 0 0)',
    height: '1px',
    margin: '-1px',
    overflow: 'hidden',
    padding: 0,
    position: 'absolute',
    whiteSpace: 'nowrap',
    width: '1px',
} as const

/** Props accepted by {@link ListPaneHeader}. */
interface ListPaneHeaderProps {
    title: string
    /** The number of records; while it is undefined the count stays empty. */
    count: number | undefined
    nouns: CountNouns
    /** A control at the end of the row, such as a New button. */
    action?: ReactNode
}

/**
 * Render a list pane's title, its record count, and its action.
 *
 * The count sits outside the heading in a polite status region that stays mounted
 * while it is empty, so screen readers announce each new count. Its noun is visually
 * hidden because the title already names the records.
 *
 * @param props - The component props.
 * @returns The heading row.
 */
export default function ListPaneHeader(props: ListPaneHeaderProps) {
    const { title, count, nouns, action } = props
    return (
        <Stack
            direction="row"
            alignItems="center"
            justifyContent="space-between"
            sx={{ px: 2, pt: 2, pb: 1 }}
        >
            <Stack direction="row" alignItems="baseline" spacing={1}>
                <Typography variant="h6" component="h1">
                    {title}
                </Typography>
                <Typography role="status" variant="body2" color="text.secondary">
                    {count !== undefined && (
                        <>
                            {formatCount(count)}
                            <Box component="span" sx={VISUALLY_HIDDEN}>
                                {` ${chooseCountNoun(count, nouns)}`}
                            </Box>
                        </>
                    )}
                </Typography>
            </Stack>
            {action}
        </Stack>
    )
}
