/** @file A record's child lists as tabs that become a select on narrow screens. */

import {
    Box,
    MenuItem,
    Tab,
    Tabs,
    TextField,
    useMediaQuery,
    useTheme,
} from '@mui/material'
import { useId } from 'react'
import type { ReactNode } from 'react'

/** One child list: the value that selects it, its label, and its content. */
interface ChildPortalTab {
    value: string
    label: string
    content: ReactNode
}

/** Props accepted by {@link ChildPortal}. */
interface ChildPortalProps {
    /** Names the tab list, and labels the select that replaces it below `sm`. */
    label: string
    tabs: ChildPortalTab[]
    /** The selected tab's value; a value that matches no tab selects the first. */
    value: string
    onChange: (value: string) => void
}

/** Props accepted by {@link TabStrip}; {@link TabSelect} takes all but `idPrefix`. */
interface TabControlProps {
    label: string
    tabs: ChildPortalTab[]
    value: string
    onChange: (value: string) => void
    /** Prefixes the ids that tie each tab to the panel. */
    idPrefix: string
}

/**
 * Render the tabs, which MUI moves between with the arrow keys.
 *
 * @param props - The component props.
 * @returns The tab list.
 */
function TabStrip(props: TabControlProps) {
    const { label, tabs, value, onChange, idPrefix } = props
    return (
        <Tabs
            value={value}
            onChange={(_event, next: string) => onChange(next)}
            aria-label={label}
            variant="scrollable"
            scrollButtons="auto"
            sx={{ borderBottom: 1, borderColor: 'divider' }}
        >
            {tabs.map((tab) => (
                <Tab
                    key={tab.value}
                    value={tab.value}
                    label={tab.label}
                    id={`${idPrefix}-tab-${tab.value}`}
                    aria-controls={`${idPrefix}-panel`}
                />
            ))}
        </Tabs>
    )
}

/**
 * Render a select, labeled like the tab list, in place of the tabs.
 *
 * @param props - The component props.
 * @returns The select.
 */
function TabSelect(props: Omit<TabControlProps, 'idPrefix'>) {
    const { label, tabs, value, onChange } = props
    return (
        <TextField
            select
            fullWidth
            size="small"
            label={label}
            value={value}
            onChange={(event) => onChange(event.target.value)}
        >
            {tabs.map((tab) => (
                <MenuItem key={tab.value} value={tab.value}>
                    {tab.label}
                </MenuItem>
            ))}
        </TextField>
    )
}

/**
 * Show one of a record's child lists at a time, chosen with tabs, or with a select
 * below the `sm` breakpoint.
 *
 * The tab is controlled, so a page can keep it in the URL. It is chosen by value, not
 * position, so a record without the selected tab shows its first one instead of
 * failing, and only the selected tab's content is mounted.
 *
 * @param props - The component props.
 * @returns The control above the selected content, or nothing without tabs.
 */
export default function ChildPortal(props: ChildPortalProps) {
    const { label, tabs, value, onChange } = props
    const theme = useTheme()
    const narrow = useMediaQuery(theme.breakpoints.down('sm'))
    const idPrefix = useId()
    if (tabs.length === 0) return null
    const active = tabs.find((tab) => tab.value === value) ?? tabs[0]
    const control = { label, tabs, value: active.value, onChange }
    return (
        <Box>
            {narrow ? (
                <TabSelect {...control} />
            ) : (
                <TabStrip {...control} idPrefix={idPrefix} />
            )}
            <Box
                id={`${idPrefix}-panel`}
                role={narrow ? undefined : 'tabpanel'}
                aria-labelledby={narrow ? undefined : `${idPrefix}-tab-${active.value}`}
                sx={{ pt: 2 }}
            >
                {active.content}
            </Box>
        </Box>
    )
}
