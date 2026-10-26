/** @file Record list with an Add button and per-row actions, used by the admin tabs. */

import AddIcon from '@mui/icons-material/Add'
import {
    Box,
    Button,
    IconButton,
    List,
    ListItem,
    ListItemText,
    ListSubheader,
    Stack,
    Typography,
} from '@mui/material'
import { Fragment } from 'react'
import type { ReactNode } from 'react'

/** One icon button shown at the end of a row. */
export interface EntityAction {
    label: string
    icon: ReactNode
    onClick: () => void
}

/** Props accepted by {@link EntityList}. */
export interface EntityListProps<T extends { id: number }> {
    title: string
    items: T[]
    emptyText: string
    addLabel: string
    onAdd: () => void
    renderPrimary: (item: T) => ReactNode
    renderSecondary?: (item: T) => ReactNode
    actions: (item: T) => EntityAction[]
    /** Why Add is disabled; Add is enabled without it. */
    addDisabledReason?: string
    /** Names each item's group; a subheader opens each run of one group. */
    groupOf?: (item: T) => string
}

/** Props accepted by {@link EntityRow}. */
interface EntityRowProps {
    primary: ReactNode
    secondary: ReactNode
    actions: EntityAction[]
}

/**
 * Render one list row with its text and trailing icon buttons.
 *
 * @param props - The component props.
 * @returns The row element.
 */
function EntityRow(props: EntityRowProps) {
    const { primary, secondary, actions } = props
    return (
        <ListItem
            divider
            secondaryAction={
                <Stack direction="row">
                    {actions.map((action) => (
                        <IconButton
                            key={action.label}
                            aria-label={action.label}
                            onClick={action.onClick}
                        >
                            {action.icon}
                        </IconButton>
                    ))}
                </Stack>
            }
        >
            <ListItemText primary={primary} secondary={secondary} />
        </ListItem>
    )
}

/**
 * Render the rows, opening each run of one group with a subheader.
 *
 * @param props - The list props.
 * @returns The rows.
 */
function EntityRows<T extends { id: number }>(props: EntityListProps<T>) {
    const { items, renderPrimary, renderSecondary, actions, groupOf } = props
    return (
        <>
            {items.map((item, index) => {
                const group = groupOf?.(item)
                const opens =
                    group !== undefined &&
                    (index === 0 || groupOf?.(items[index - 1]) !== group)
                return (
                    <Fragment key={item.id}>
                        {opens && <ListSubheader disableSticky>{group}</ListSubheader>}
                        <EntityRow
                            primary={renderPrimary(item)}
                            secondary={renderSecondary?.(item)}
                            actions={actions(item)}
                        />
                    </Fragment>
                )
            })}
        </>
    )
}

/**
 * Render a titled list of records with an Add button and row actions.
 *
 * @param props - The component props.
 * @returns The list element.
 */
export default function EntityList<T extends { id: number }>(props: EntityListProps<T>) {
    const { title, items, emptyText, addLabel, onAdd, addDisabledReason } = props
    return (
        <Box>
            <Stack direction="row" alignItems="center" justifyContent="space-between">
                <Typography variant="h6" component="h2">
                    {title}
                </Typography>
                <Button
                    size="small"
                    variant="contained"
                    startIcon={<AddIcon />}
                    onClick={onAdd}
                    disabled={Boolean(addDisabledReason)}
                >
                    {addLabel}
                </Button>
            </Stack>
            {addDisabledReason && (
                <Typography color="text.secondary" variant="body2" sx={{ mt: 1 }}>
                    {addDisabledReason}
                </Typography>
            )}
            {items.length === 0 && (
                <Typography color="text.secondary" sx={{ mt: 2 }}>
                    {emptyText}
                </Typography>
            )}
            <List dense>
                <EntityRows {...props} />
            </List>
        </Box>
    )
}
