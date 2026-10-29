/** @file Two-pane layout: a list on the left and the selected record on the right. */

import ArrowBackIcon from '@mui/icons-material/ArrowBack'
import { Box, Button, useMediaQuery, useTheme } from '@mui/material'
import type { SxProps, Theme } from '@mui/material'
import { useEffect, useRef } from 'react'
import type { ReactNode } from 'react'

/** Props accepted by {@link MasterDetailLayout}. */
interface MasterDetailLayoutProps {
    list: ReactNode
    detail: ReactNode
    showDetail: boolean
    onBack: () => void
    emptyState: ReactNode
}

/** The list pane's width beside the detail pane, in pixels. */
const LIST_PANE_WIDTH = 384

/**
 * Style the list pane: a fixed column beside the detail, or the full width alone.
 *
 * @param shown - Whether the pane is on screen.
 * @param sideBySide - Whether both panes fit side by side.
 * @returns The pane's `sx` styles.
 */
function listPaneStyles(shown: boolean, sideBySide: boolean): SxProps<Theme> {
    return {
        display: shown ? 'flex' : 'none',
        flexDirection: 'column',
        width: sideBySide ? LIST_PANE_WIDTH : '100%',
        flexShrink: 0,
        borderRight: sideBySide ? 1 : 'none',
        borderColor: 'divider',
        overflowY: 'auto',
    }
}

/**
 * Style the detail pane, which takes the remaining width.
 *
 * @param shown - Whether the pane is on screen.
 * @returns The pane's `sx` styles.
 */
function detailPaneStyles(shown: boolean): SxProps<Theme> {
    return {
        display: shown ? 'flex' : 'none',
        flexDirection: 'column',
        flex: 1,
        minWidth: 0,
        overflowY: 'auto',
    }
}

/**
 * Move focus to the pane that comes on screen while the panes take turns.
 *
 * Below `md`, opening a record hides the list, and the focused row with it, so focus
 * moves to the detail pane; Back moves it to the list pane. A record that appears
 * after the first render counts as opened, as when a linked record shows once its
 * list loads. Side by side, and on the first render, focus stays where it is.
 *
 * @param showDetail - Whether a record is selected.
 * @param sideBySide - Whether both panes fit side by side.
 * @returns The refs for the list pane and the detail pane.
 */
function usePaneFocus(showDetail: boolean, sideBySide: boolean) {
    const listRef = useRef<HTMLDivElement>(null)
    const detailRef = useRef<HTMLDivElement>(null)
    const shownBefore = useRef(showDetail)

    useEffect(() => {
        if (shownBefore.current === showDetail) return
        shownBefore.current = showDetail
        if (sideBySide) return
        // Both panes always render, so both refs are attached by the time effects run.
        const pane = showDetail ? detailRef : listRef
        pane.current!.focus()
    }, [showDetail, sideBySide])

    return { listRef, detailRef }
}

/**
 * Show the list and the detail side by side, or one at a time on narrow screens.
 *
 * From the `md` breakpoint up both panes show. Below it only one does: the list until
 * a record is selected, then the detail with a Back button that clears the selection.
 * Both panes stay mounted, so the list keeps its scroll position, and they sit in a
 * row at every width, so the pane on screen fills the height and scrolls on its own
 * when the parent's height is definite, as the app shell's main region is.
 *
 * @param props - The component props.
 * @returns The layout element.
 */
export default function MasterDetailLayout(props: MasterDetailLayoutProps) {
    const { list, detail, showDetail, onBack, emptyState } = props
    const theme = useTheme()
    const sideBySide = useMediaQuery(theme.breakpoints.up('md'))
    const { listRef, detailRef } = usePaneFocus(showDetail, sideBySide)
    return (
        <Box sx={{ display: 'flex', height: '100%' }}>
            <Box
                ref={listRef}
                tabIndex={-1}
                sx={listPaneStyles(sideBySide || !showDetail, sideBySide)}
            >
                {list}
            </Box>
            <Box
                ref={detailRef}
                tabIndex={-1}
                sx={detailPaneStyles(sideBySide || showDetail)}
            >
                {showDetail ? (
                    <>
                        {!sideBySide && (
                            <Button
                                startIcon={<ArrowBackIcon />}
                                onClick={onBack}
                                sx={{ alignSelf: 'flex-start', m: 1 }}
                            >
                                Back
                            </Button>
                        )}
                        {detail}
                    </>
                ) : (
                    emptyState
                )}
            </Box>
        </Box>
    )
}
