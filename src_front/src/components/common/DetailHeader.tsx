/** @file A detail pane's heading: the title, an optional subtitle, Edit, and Delete. */

import DeleteIcon from '@mui/icons-material/Delete'
import EditIcon from '@mui/icons-material/Edit'
import { Box, Button, Stack, Typography } from '@mui/material'

/** Props accepted by {@link DetailHeader}. */
interface DetailHeaderProps {
    title: string
    subtitle?: string | null
    /** Shows an Edit button that calls it. */
    onEdit?: () => void
    /** Shows a Delete button that calls it; leave it out for records never deleted. */
    onDelete?: () => void
}

/**
 * Render the record's title, with the subtitle below it when given, beside an Edit
 * and a Delete button for the handlers given.
 *
 * The title breaks inside a long word, such as an email address, instead of pushing
 * the buttons off a narrow screen.
 *
 * @param props - The component props.
 * @returns The header element.
 */
export default function DetailHeader(props: DetailHeaderProps) {
    const { title, subtitle, onEdit, onDelete } = props
    return (
        <Stack direction="row" justifyContent="space-between" alignItems="flex-start">
            <Box sx={{ minWidth: 0, overflowWrap: 'break-word' }}>
                <Typography variant="h5" component="h1">
                    {title}
                </Typography>
                {subtitle && <Typography color="text.secondary">{subtitle}</Typography>}
            </Box>
            <Stack direction="row" spacing={1}>
                {onEdit && (
                    <Button startIcon={<EditIcon />} onClick={onEdit}>
                        Edit
                    </Button>
                )}
                {onDelete && (
                    <Button color="error" startIcon={<DeleteIcon />} onClick={onDelete}>
                        Delete
                    </Button>
                )}
            </Stack>
        </Stack>
    )
}
