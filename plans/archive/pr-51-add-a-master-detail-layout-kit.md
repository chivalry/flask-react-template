# Issue #18: Add a master-detail layout kit

## Context

Nearly every screen in the derived apps is a list beside the selected record, and
hukilau, ranch-tracker, and treasured-souvenirs each built it from scratch. This ports
hukilau's MUI kit, read at hukilau `origin/staging` (a6cef24; the working tree's copies
are identical), and ranch-tracker's `ChildPortal` (`staging` worktree, 922eaae), which
is Tailwind and is rebuilt here in MUI. Read hukilau files with
`git -C /Users/chuck/Projects/family/hukilau show origin/staging:<path>`.

Already in the template and reused unchanged: `useUsers`, `UserFormDialog`,
`useRecordDialogs`, `QueryState`, `RecordAuditLogTab`, `AuditLogTab`, `useAuditLog`,
and `formatLocalDateTime`. `useSearchParamWriter` exists from #7 with no consumer yet.
No backend change: every route the example calls exists.

Decisions made with Chuck on 2026-10-29, beyond the issue text:

- The example is on Home, for admins only. Every `/api/v1/users` route is
  `@admin_required`, so Home wired to the users list would show non-admins a 403; they
  keep today's welcome.
- `MasterDetailLayout` reads the `md` breakpoint with MUI's `useMediaQuery`, not
  hukilau's responsive `sx`, so tests can check the issue's 1280 px and 375 px criteria.
- Selecting an account pushes a history entry, as hukilau's path-based selection does,
  so a phone's back gesture returns from a record to the list. `useSearchParamWriter`
  gains a `{ push: true }` option; tabs keep replacing.
- `DetailColumns` splits at `lg`, as hukilau has it, not at the issue's `md`: beside
  the 384 px list, each column at `md` would be about 230 px (hukilau's PR #25 plan).
- `AppShell` is `100dvh` tall, not the issue's `100vh`: on iOS Safari `100vh` is the
  height with the toolbars retracted, so while they show, each pane's bottom sits
  behind them.
- Focus follows the pane below `md`: opening a record moves focus to the detail pane,
  and Back moves it to the list pane. No sibling app does this.

Why a breakpoint must go through `useMediaQuery` to be testable, established from the
installed sources: MUI 6.5.0 turns every breakpoint key, `xs` included, into
`@media (min-width:…)` (`@mui/system/esm/breakpoints/breakpoints.js:56` and
`createBreakpoints.js:41-44`), and jsdom 29.1.1 applies a media rule only when its
query is `all` or `screen` (`jsdom/lib/jsdom/living/css/MediaList-impl.js:125-138`).
Responsive `sx` values therefore never apply in tests, while plain ones do, as the
`EnvironmentBadge` test's `toHaveStyle` shows. hukilau's plans accepted that and checked
layouts only in the browser. Under React 19's `createRoot`, `useSyncExternalStore`
reads `getSnapshot` on the first render, so `useMediaQuery` returns the real match at
once and needs no `noSsr` (`@mui/system/esm/useMediaQuery/useMediaQuery.js:43-71`).
That hook takes its theme from `useThemeWithoutDefault`, which is `null` without a
`ThemeProvider` (`useThemeWithoutDefault.js:8-10` in the same package), and the
tests render without one, so the callback form, `useMediaQuery((theme) => …)`, throws
there (`useMediaQuery.js:79` and `:103`). The components take `theme` from MUI's
`useTheme()`, which falls back to the default theme, and pass the query as a string.

Choices this plan makes:

- `ListPaneHeader` takes an `action` slot, as the issue asks, in place of hukilau's
  `onNew` and built-in New button.
- `DetailHeader`'s `onEdit` and `onDelete` are optional, and each button shows only
  with its handler, as `RecordSection` offers Delete only with `remove`: accounts are
  never deleted. Its title box gets `minWidth: 0` and `overflowWrap: 'break-word'`, so
  a long email wraps instead of pushing Edit off a phone.
- `ChildPortal` shows MUI `Tabs` from `sm` up and a labeled `TextField` select below,
  as the issue says; ranch-tracker switched at 768 px to a custom button menu without
  tab or listbox semantics. It is controlled (`value`, `onChange`), so the example
  keeps the tab in the URL, and it picks the tab by value. ranch-tracker kept an
  index it never reset, so a record with fewer tabs indexed past the end and threw;
  here a value that matches no tab selects the first. Only the selected tab's content
  is mounted, as in ranch-tracker.
- The panes sit in a row at every width. hukilau's narrow layout is a column in which
  the list pane cannot shrink, so a long list grows past the screen instead of
  scrolling; ranch-tracker fixed the same bug in 85569b2. In a row, the one pane on
  screen stretches to the height and scrolls.
- Each list row is a `ListItem` (an `li`) holding its `ListItemButton`, so screen
  readers hear a list of items; hukilau's rows sit in the `ul` directly. The selected
  row's button carries `aria-current="true"` beside MUI's `selected` styling, so they
  also hear which account is open.
- `useSearchParamWriter` skips a write that leaves the value as it is, so clicking the
  open account pushes no second entry for the same URL.
- `describeUser` moves from `UsersAdmin.tsx` to `utils/users.ts`: the example
  describes accounts the same way, and a component file may export only components.
- `useUserMutations` also invalidates `['audit-logs']`, as `ai/conventions.md` asks of
  a form beside a record's history, so History and Activity refresh after a save.
- The writer test's `LocationProbe` moves to `test/utils/`, because the example's
  tests need it too and fallow fails on a copied block (50 tokens and 5 lines by
  default).
- Fallow also fails on an export nothing imports, so the new modules export only the
  components, `CountNouns`, `formatCount`, `chooseCountNoun`, `describeUser`,
  `stubViewportWidth`, and `LocationProbe`; props interfaces stay private.

## Branch

`issue-18-add-a-master-detail-layout-kit` — already checked out; PR #51 exists.

## Change

Paths below are under `src_front/src/` unless they start with `ai/` or `README`.

**New source (10)**: `utils/counts.ts`, `utils/users.ts`,
`components/layout/{MasterDetailLayout,ListPaneHeader,ChildPortal}.tsx`,
`components/common/{DetailHeader,DetailColumns,LabeledRow}.tsx`,
`components/admin/{UsersMasterDetail,UserDetail}.tsx`.
**Edited source (5)**: `components/layout/AppShell.tsx`,
`hooks/useSearchParamWriter.ts`, `hooks/users.ts`, `components/admin/UsersAdmin.tsx`,
`pages/Home.tsx`.
**New tests and helpers (13)**: `test/utils/viewport.ts`, `test/utils/LocationProbe.tsx`,
`test/utils/{counts,users}.test.ts`,
`test/components/layout/{MasterDetailLayout,ListPaneHeader,ChildPortal}.test.tsx`,
`test/components/common/{DetailHeader,DetailColumns,LabeledRow}.test.tsx`,
`test/components/admin/{UsersMasterDetail,UserDetail}.test.tsx`,
`test/pages/Home.test.tsx`.
**Edited tests (5)**: `test/setup.ts`, `test/hooks/useSearchParamWriter.test.tsx`,
`test/hooks/users.test.tsx`, `test/components/layout/AppShell.test.tsx`,
`test/App.test.tsx`.
**Docs (3)**: `ai/conventions.md`, `ai/project.md`, `README.md`.

Every new source file follows the lint rules: a `@file` block; JSDoc on every function,
interface, and type alias, with `@param` and `@returns` described and untyped; no
function over 50 lines; component files export only components. New test files open
with a `@file` line too, as the newer tests do.

### test/utils/viewport.ts — new: stub `matchMedia` at a width

```ts
/** @file Make media queries answer as a viewport of a chosen width would. */

import { vi } from 'vitest'

/**
 * Tell whether a media query's width conditions hold at a viewport width.
 *
 * Only `min-width` and `max-width` in pixels are read, which is all that MUI's
 * `breakpoints.up()` and `breakpoints.down()` produce.
 */
function matchesWidth(query: string, width: number): boolean {
    const min = /min-width:\s*([\d.]+)px/.exec(query)
    const max = /max-width:\s*([\d.]+)px/.exec(query)
    return (!min || width >= Number(min[1])) && (!max || width <= Number(max[1]))
}

/**
 * Stub `window.matchMedia` so MUI's `useMediaQuery` sees a viewport `width` pixels
 * wide.
 *
 * jsdom has no `matchMedia`, and without one `useMediaQuery` reports no match.
 * `test/setup.ts` stubs 1280 before every test; a test of a phone layout calls this
 * with 375 before it renders. The stub never fires a change event.
 */
export function stubViewportWidth(width: number) {
    vi.stubGlobal('matchMedia', (query: string) => ({
        matches: matchesWidth(query, width),
        media: query,
        addEventListener: () => undefined,
        removeEventListener: () => undefined,
    }))
}
```

Vitest's jsdom environment sets `global.window = global`
(`vitest/dist/chunks/index.DC7d2Pf8.js:274`), so the stub is `window.matchMedia`, the
name MUI reads at call time.

### test/setup.ts — default every test to a desktop width

Import `stubViewportWidth` from `./utils/viewport` and call it last in the existing
`beforeEach` (lines 12-14):

```ts
beforeEach(() => {
    vi.stubGlobal('IntersectionObserver', IntersectionObserverStub)
    // jsdom has no matchMedia either. Every test starts on a desktop-wide viewport,
    // and a test of a phone layout calls stubViewportWidth(375) before it renders.
    stubViewportWidth(1280)
})
```

No current component calls `useMediaQuery`, so no existing test changes behavior.

### utils/counts.ts and test/utils/counts.test.ts — new, verbatim

Copy hukilau's `src_front/src/utils/counts.ts` (31 lines: `CountNouns`, `formatCount`
with a fixed `en-US` format, `chooseCountNoun`) and
`src_front/src/test/utils/counts.test.ts` (thousands grouping; `it.each` over 0, 1,
and 2) unchanged.

### components/layout/MasterDetailLayout.tsx — new

hukilau's layout with the breakpoint read in JavaScript, the panes in a row at every
width, and focus following the pane:

```tsx
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
```

`tabIndex={-1}` makes each pane focusable by script but not by Tab. The non-null
assertion follows `InfiniteScrollSentinel.tsx:33`; an optional chain there would leave
a branch no test can reach.

### test/components/layout/MasterDetailLayout.test.tsx — new: the acceptance criteria

A harness owns the selection, so clicks and Back behave as on a page:

```tsx
/** @file Both panes show from md up; below it one shows at a time, with Back. */

import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { beforeEach, describe, expect, it } from 'vitest'

import MasterDetailLayout from '../../../components/layout/MasterDetailLayout'
import { stubViewportWidth } from '../../utils/viewport'

/** A list of one record, Ada, whose selection lives in local state. */
function Harness({ selectedAtFirst = false }: { selectedAtFirst?: boolean }) {
    const [selected, setSelected] = useState(selectedAtFirst)
    return (
        <MasterDetailLayout
            list={<button onClick={() => setSelected(true)}>Ada</button>}
            detail={<h2>Ada's details</h2>}
            showDetail={selected}
            onBack={() => setSelected(false)}
            emptyState={<p>Pick someone.</p>}
        />
    )
}

/** The list pane, the parent of Ada's row. */
const listPane = () => screen.getByText('Ada').parentElement!
```

Cases, with these assertions (`toBeVisible` reads the plain `display` the layout sets,
which jsdom applies):

- At the default 1280 px: the list pane is visible with `toHaveStyle({ width:
  '384px' })`, `Pick someone.` is visible, and there is no Back button.
- At 1280 px, clicking Ada shows the heading beside a visible list, leaves focus on
  the Ada button (`toHaveFocus()`), and renders no Back button.
- `it.each` at 900 px (both panes visible) and 899 px (only the list visible), the
  edges of `up('md')`; this kills `up('lg')` and `up('sm')`.
- At 375 px (`beforeEach(() => stubViewportWidth(375))` in its own `describe`): only
  the list shows, `toHaveStyle({ width: '100%' })`, and `Pick someone.` is
  `not.toBeVisible()`.
- At 375 px, clicking Ada hides the list (`screen.getByText('Ada')` is
  `not.toBeVisible()`), shows the heading and a visible Back button, and the heading's
  parent, the detail pane, has focus.
- At 375 px, Back shows the list again, hides `Pick someone.`, and the list pane has
  focus.
- At 375 px, `<Harness selectedAtFirst />` shows the detail and moves no focus
  (`expect(document.body).toHaveFocus()`).

### components/layout/ListPaneHeader.tsx — new

hukilau's header with an action slot in place of `onNew`:

```tsx
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
```

Sizes are `'1px'` strings because `sx` reads numbers in (0, 1] as percentages.

`test/components/layout/ListPaneHeader.test.tsx`, with
`const NOUNS = { one: 'user', other: 'users' }`:

- The title is `getByRole('heading', { level: 1, name: 'Users' })`, and an `action`
  of `<button>New user</button>` renders; without `action`, `queryByRole('button')` is
  null.
- `it.each` over `[0, '0 users']`, `[1, '1 user']`, `[1234, '1,234 users']`:
  `getByRole('status')` has that text content.
- The noun is hidden from sight only: `getByText('users')` (the span's text is
  `' users'`, which the default normalizer trims) has `toHaveStyle({ position:
  'absolute', width: '1px', height: '1px', overflow: 'hidden' })`, and the heading's
  text does not contain the count.
- With `count={undefined}` the status region exists and `toBeEmptyDOMElement()`;
  after `rerender` with `count={3}` the same element (`toBe`) reads `3 users`, which
  is what lets a screen reader announce it.

### components/layout/ChildPortal.tsx — new

```tsx
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
```

`down('sm')` is `(max-width:599.95px)`. A `tabpanel` needs a tab list, so below `sm`
the panel is a plain box.

`test/components/layout/ChildPortal.test.tsx` renders a controlled harness:
`useState` holds the value and passes `setValue` as `onChange`, with tabs History
(`<p>History list</p>`) and Activity (`<p>Activity list</p>`) and the label
`Account history`. Cases:

- At 1280 px with an empty value: `getByRole('tablist', { name: 'Account history' })`;
  the History tab has `aria-selected="true"`; `getByRole('tabpanel', { name:
  'History' })` holds `History list`; `Activity list` is not in the document.
- Clicking the Activity tab shows `Activity list` and unmounts `History list`.
- `rerender` from both tabs with value `activity` to History alone shows `History
  list` instead of throwing (ranch-tracker's bug).
- `it.each` at 600 px (a tab list) and 599 px (no tab list; a combobox), the edges of
  `down('sm')`.
- At 375 px: no `tablist`; `getByRole('combobox', { name: /Account history/ })` (MUI
  names it by its label and its value, as `FormSelectField.test.tsx:17` relies on)
  reads `History`; clicking it and then `getByRole('option', { name: 'Activity' })`
  shows `Activity list`.
- `tabs={[]}` renders nothing: the render's `container` is `toBeEmptyDOMElement()`.

### components/common/DetailHeader.tsx — new

```tsx
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
```

`test/components/common/DetailHeader.test.tsx`:

- The title is `getByRole('heading', { level: 1, name })` and the subtitle's text
  shows; with no subtitle the heading's parent has one child.
- With both handlers, clicking Edit and Delete calls each `vi.fn()` once.
- With `onEdit` alone there is no Delete button; with neither,
  `queryAllByRole('button')` is empty.
- The heading's parent has `toHaveStyle({ minWidth: '0px', overflowWrap:
  'break-word' })`.

### components/common/DetailColumns.tsx and LabeledRow.tsx — new, verbatim

Copy hukilau's `src_front/src/components/common/DetailColumns.tsx` (columns from `lg`,
`minWidth: 0`, `overflowWrap: 'break-word'`, left column first so reading order
matches tab order) and `LabeledRow.tsx` (a caption beside a wrapping row) unchanged.
The `lg` split is responsive `sx`, which jsdom never applies; Verification checks it in
Chrome.

- `test/components/common/DetailColumns.test.tsx`: with `left={<h2>Contact log</h2>}`
  and `right={<h2>Addresses</h2>}`, `getAllByRole('heading')` reads in that order, and
  each heading's parent has `toHaveStyle({ minWidth: '0px', overflowWrap:
  'break-word' })`.
- `test/components/common/LabeledRow.test.tsx`: with `label="Tags"` and two `Chip`s
  (`Buyer`, `Cash`), `getByText('Tags').parentElement` has the text `TagsBuyerCash`.

### test/utils/LocationProbe.tsx — new, moved from the writer test

```tsx
/** @file Show the router's query string and how it got there, for tests to read. */

import { useLocation, useNavigationType } from 'react-router-dom'

/**
 * Render the current query string and navigation type in named outputs.
 *
 * An `output` has the `status` role, so each carries a name, read with
 * `screen.getByLabelText('Search')` or `screen.getByLabelText('Navigation type')`;
 * a component's own unnamed status region is then `getByRole('status', { name: '' })`.
 */
export default function LocationProbe() {
    const { search } = useLocation()
    const navigationType = useNavigationType()
    return (
        <>
            <output aria-label="Search">{search}</output>
            <output aria-label="Navigation type">{navigationType}</output>
        </>
    )
}
```

### hooks/useSearchParamWriter.ts — a `push` option

Replace the module:

```ts
/** @file Write one URL query parameter in place, keeping the others. */

import { useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'

/** How {@link useSearchParamWriter} records each write in the browser history. */
interface SearchParamWriterOptions {
    /** Push a history entry for each write, so Back returns to the previous value. */
    push?: boolean
}

/**
 * Return a function that writes one query parameter and keeps the others.
 *
 * An empty value deletes the parameter instead of leaving `key=` in the URL, and a
 * value the URL already holds writes nothing. By default every write replaces the
 * current history entry rather than pushing one, so Back leaves the page instead of
 * undoing one change at a time, as suits a filter typed a letter at a time. With
 * `push`, each write is an entry of its own, as suits a selection that Back should
 * undo, such as the record a master-detail page shows; clicking the record already
 * shown then adds no entry.
 *
 * @param options - How writes enter the history; by default they replace the entry.
 * @returns The writer, called with the parameter's name and its new value.
 */
export function useSearchParamWriter(options: SearchParamWriterOptions = {}) {
    const { push = false } = options
    const [params, setParams] = useSearchParams()
    return useCallback(
        (key: string, value: string) => {
            if ((params.get(key) ?? '') === value) return
            setParams(
                (current) => {
                    const next = new URLSearchParams(current)
                    if (value) next.set(key, value)
                    else next.delete(key)
                    return next
                },
                { replace: !push },
            )
        },
        [params, setParams, push],
    )
}
```

`test/hooks/useSearchParamWriter.test.tsx`:

- Delete the local `LocationProbe` (lines 10-20) and import it from
  `'../utils/LocationProbe'`; `useLocation` and `useNavigationType` leave the
  `react-router-dom` import.
- `renderWriter(url: string, options?: { push?: boolean })` passes `options` to
  `useSearchParamWriter`; its comment becomes "Mount the writer, built with
  `options`, in a memory router that starts at `url`, beside the probe."
- `@file`: "Check that the writer sets, deletes, or leaves one parameter, replacing the
  history entry unless it is built to push."
- New cases, as one `it.each` so they add no block that repeats the existing cases:

```tsx
    it.each([
        {
            label: 'pushes a history entry when built to push',
            url: '/?tab=history',
            search: '?tab=history&user=2',
            navigation: 'PUSH',
        },
        {
            label: 'writes nothing when the parameter already holds the value',
            url: '/?user=2',
            search: '?user=2',
            navigation: 'POP',
        },
    ])('$label', ({ url, search, navigation }) => {
        const { result } = renderWriter(url, { push: true })

        act(() => result.current('user', '2'))

        expect(probe('Search')).toBe(search)
        expect(probe('Navigation type')).toBe(navigation)
    })
```

### hooks/users.ts — refresh the audit log after a save

In `useUserMutations` (lines 35-49), pass `alsoInvalidate: [['audit-logs']]` before
`onUpdated`, and in its JSDoc replace "An update to the signed-in account also replaces
the auth store's copy of it." with "A save also refreshes the audit log, so an
account's history beside the form shows the change, and an update to the signed-in
account replaces the auth store's copy of it."

`test/hooks/users.test.tsx`: the create case (line 50) becomes "create sends the
payload, then invalidates the account list and the audit log", and line 60 expects
`[[{ queryKey: ['users'] }], [{ queryKey: ['audit-logs'] }]]`
(`hooks/resources.ts:37-41` invalidates the resource's key first).

### utils/users.ts — new; components/admin/UsersAdmin.tsx — use it

```ts
/** @file How an account reads in lists and headings. */

import type { User } from '../types/users'

/**
 * Describe an account's role and whether it is deactivated.
 *
 * @param user - The account.
 * @returns For example `admin` or `user · inactive`.
 */
export function describeUser(user: User): string {
    return user.is_active ? user.role : `${user.role} · inactive`
}
```

In `UsersAdmin.tsx` delete `describeUser` and its JSDoc (lines 9-17) and add
`import { describeUser } from '../../utils/users'` after the `types/users` import.
`test/utils/users.test.ts`: `describeUser(adminUser)` is `admin`, and
`describeUser({ ...plainUser, is_active: false })` is `user · inactive`.

### components/layout/AppShell.tsx — fill the visible viewport

- Line 138: `minHeight: '100vh'` becomes `height: '100dvh'`.
- Line 153: the main region's `sx` becomes
  `{ display: 'flex', flexDirection: 'column', flex: 1, minHeight: 0 }`.
- JSDoc (lines 126-135), after the first paragraph's phone sentence: "The shell is as
  tall as the visible viewport (`100dvh`, which leaves out a phone browser's toolbars,
  where `100vh` does not), and the main region is a flex column with no minimum
  height, so a page such as a `MasterDetailLayout` fills it and scrolls its own panes
  under the bar; a taller page still scrolls the document."

`test/components/layout/AppShell.test.tsx`, a new case: `const main =
screen.getByRole('main')`; `main.parentElement` has `toHaveStyle({ height: '100dvh'
})`, and `main` has `toHaveStyle({ display: 'flex', flexDirection: 'column',
minHeight: '0px' })`. jsdom keeps `100dvh` in a computed style (checked while
planning).

### components/admin/UsersMasterDetail.tsx — new: the example

```tsx
/** @file The accounts as a master-detail page, the layout kit's example on Home. */

import AddIcon from '@mui/icons-material/Add'
import {
    Button,
    List,
    ListItem,
    ListItemButton,
    ListItemText,
    Typography,
} from '@mui/material'
import type { UseQueryResult } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'

import { useRecordDialogs } from '../../hooks/useRecordDialogs'
import { useSearchParamWriter } from '../../hooks/useSearchParamWriter'
import { useUserMutations, useUsers } from '../../hooks/users'
import type { User, UserPayload } from '../../types/users'
import type { CountNouns } from '../../utils/counts'
import { describeUser } from '../../utils/users'
import QueryState from '../common/QueryState'
import ListPaneHeader from '../layout/ListPaneHeader'
import MasterDetailLayout from '../layout/MasterDetailLayout'
import UserDetail from './UserDetail'
import UserFormDialog from './UserFormDialog'

/** The query parameter that holds the selected account's id. */
const SELECTED_PARAM = 'user'

/** The query parameter that holds the selected tab of the account's history. */
const TAB_PARAM = 'tab'

/** The nouns the account count reads with. */
const USER_NOUNS: CountNouns = { one: 'user', other: 'users' }

/** What the detail pane shows while no account is selected. */
const NO_SELECTION = (
    <Typography color="text.secondary" sx={{ p: 3 }}>
        Select a user to see their details.
    </Typography>
)

/** Props accepted by {@link UserRow}. */
interface UserRowProps {
    user: User
    selected: boolean
    onSelect: (id: number) => void
}

/** Props accepted by {@link UserListPane}. */
interface UserListPaneProps {
    query: UseQueryResult<User[]>
    selectedId: number | undefined
    onSelect: (id: number) => void
    onNew: () => void
}

/**
 * Render one account as a row that opens it, marked while it is open.
 *
 * @param props - The component props.
 * @returns The row.
 */
function UserRow(props: UserRowProps) {
    const { user, selected, onSelect } = props
    return (
        <ListItem disablePadding divider>
            <ListItemButton
                selected={selected}
                aria-current={selected ? 'true' : undefined}
                onClick={() => onSelect(user.id)}
            >
                <ListItemText primary={user.email} secondary={describeUser(user)} />
            </ListItemButton>
        </ListItem>
    )
}

/**
 * Render the account list: its heading, count, and New user, then a row per account.
 *
 * @param props - The component props.
 * @returns The list pane's content.
 */
function UserListPane(props: UserListPaneProps) {
    const { query, selectedId, onSelect, onNew } = props
    return (
        <>
            <ListPaneHeader
                title="Users"
                count={query.isError ? undefined : query.data?.length}
                nouns={USER_NOUNS}
                action={
                    <Button
                        size="small"
                        variant="contained"
                        startIcon={<AddIcon />}
                        onClick={onNew}
                    >
                        New user
                    </Button>
                }
            />
            <QueryState query={query}>
                {(users) => (
                    <List disablePadding>
                        {users.map((user) => (
                            <UserRow
                                key={user.id}
                                user={user}
                                selected={user.id === selectedId}
                                onSelect={onSelect}
                            />
                        ))}
                    </List>
                )}
            </QueryState>
        </>
    )
}

/**
 * Read the selected account and tab from the URL, with their writers.
 *
 * Selecting an account, or clearing the selection, pushes a history entry, so Back
 * returns from an account to the list; choosing a tab replaces the entry.
 *
 * @returns The selected id and tab as the URL holds them, and their writers.
 */
function useSelectionParams() {
    const [params] = useSearchParams()
    const writeSelection = useSearchParamWriter({ push: true })
    const writeTab = useSearchParamWriter()
    return {
        selectedId: params.get(SELECTED_PARAM),
        tab: params.get(TAB_PARAM) ?? '',
        select: (id: number | null) =>
            writeSelection(SELECTED_PARAM, id === null ? '' : String(id)),
        selectTab: (tab: string) => writeTab(TAB_PARAM, tab),
    }
}

/**
 * Hold the account dialog and save what it submits.
 *
 * @param select - Selects an account by id; a new account is selected once saved.
 * @returns The dialog state and the submit handler.
 */
function useUserForm(select: (id: number) => void) {
    const dialogs = useRecordDialogs<User>()
    const { create, update } = useUserMutations()

    /**
     * Create or update, depending on which dialog is open, then close it.
     *
     * The form dialog cannot be dismissed while this runs (see `RecordDialogProps`),
     * so the dialog still open when the save settles is the one that started it.
     *
     * @param payload - The validated request body.
     */
    const submit = async (payload: UserPayload) => {
        if (dialogs.editing) {
            await update.mutateAsync({ id: dialogs.editing.id, payload })
        } else {
            const created = await create.mutateAsync(payload)
            select(created.id)
        }
        dialogs.close()
    }

    return { dialogs, submit }
}

/**
 * Render the accounts beside the selected one, with the dialog that creates and edits
 * them.
 *
 * The selected account and tab live in the URL, as in `/?user=2&tab=activity`, so a
 * reload or a shared link shows the same view, and an id that matches no account
 * selects nothing. This is the layout kit's example; a project replaces it with its
 * own records.
 *
 * @returns The page content.
 */
export default function UsersMasterDetail() {
    const query = useUsers()
    const { selectedId, tab, select, selectTab } = useSelectionParams()
    const { dialogs, submit } = useUserForm(select)
    const selected = query.data?.find((user) => String(user.id) === selectedId) ?? null
    return (
        <>
            <MasterDetailLayout
                list={
                    <UserListPane
                        query={query}
                        selectedId={selected?.id}
                        onSelect={select}
                        onNew={dialogs.openCreate}
                    />
                }
                detail={
                    selected && (
                        <UserDetail
                            user={selected}
                            tab={tab}
                            onTabChange={selectTab}
                            onEdit={() => dialogs.openEdit(selected)}
                        />
                    )
                }
                showDetail={selected !== null}
                onBack={() => select(null)}
                emptyState={NO_SELECTION}
            />
            <UserFormDialog
                open={dialogs.creating || dialogs.editing !== null}
                item={dialogs.editing}
                onClose={dialogs.close}
                onSubmit={submit}
            />
        </>
    )
}
```

Comparing `String(user.id)` with the raw parameter needs no parsing: `abc`, `-1`, and
`2.0` match no account. `create.mutateAsync` resolves before the list refetch lands
(`hooks/resources.ts:39` does not await it), so the detail of a new account appears
when the refetch does. If `max-lines-per-function` flags `UsersMasterDetail`, move the
`list` element into a `const` above the `return`.

### components/admin/UserDetail.tsx — new: the example's detail pane

```tsx
/** @file One account's detail: its heading, how it signs in, history, and activity. */

import { Chip, Stack, Typography } from '@mui/material'

import { useAuditLog } from '../../hooks/auditLogs'
import type { User } from '../../types/users'
import { formatLocalDateTime } from '../../utils/dates'
import { describeUser } from '../../utils/users'
import AuditLogTab from '../common/AuditLogTab'
import DetailColumns from '../common/DetailColumns'
import DetailHeader from '../common/DetailHeader'
import LabeledRow from '../common/LabeledRow'
import RecordAuditLogTab from '../common/RecordAuditLogTab'
import ChildPortal from '../layout/ChildPortal'

/** Props accepted by {@link UserDetail}. */
interface UserDetailProps {
    user: User
    /** The selected tab of the account's history, as the URL holds it. */
    tab: string
    onTabChange: (tab: string) => void
    onEdit: () => void
}

/** Props accepted by {@link AccountActivity}. */
interface AccountActivityProps {
    userId: number
}

/**
 * Show the changes an account made, to any record, newest first.
 *
 * @param props - The component props.
 * @returns The activity table.
 */
function AccountActivity(props: AccountActivityProps) {
    const query = useAuditLog({
        tableName: '',
        changedById: String(props.userId),
        from: '',
        to: '',
    })
    return <AuditLogTab query={query} showRecord emptyText="No activity yet." />
}

/**
 * Build the tabs of an account's history: the changes made to it, then by it.
 *
 * @param userId - The account's id.
 * @returns The History and Activity tabs.
 */
function accountTabs(userId: number) {
    return [
        {
            value: 'history',
            label: 'History',
            content: <RecordAuditLogTab tableName="users" recordId={userId} />,
        },
        {
            value: 'activity',
            label: 'Activity',
            content: <AccountActivity userId={userId} />,
        },
    ]
}

/**
 * Render the account's heading and Edit, how it signs in and when it was created, and
 * its history and activity.
 *
 * Accounts are deactivated, never deleted, so the header offers no Delete.
 *
 * @param props - The component props.
 * @returns The detail element.
 */
export default function UserDetail(props: UserDetailProps) {
    const { user, tab, onTabChange, onEdit } = props
    return (
        <Stack spacing={3} sx={{ p: 2 }}>
            <DetailHeader
                title={user.email}
                subtitle={describeUser(user)}
                onEdit={onEdit}
            />
            <DetailColumns
                left={
                    <LabeledRow label="Sign-in">
                        <Chip
                            size="small"
                            label={user.has_password ? 'Password' : 'No password'}
                        />
                    </LabeledRow>
                }
                right={
                    <LabeledRow label="Created">
                        <Typography variant="body2">
                            {formatLocalDateTime(user.created_at)}
                        </Typography>
                    </LabeledRow>
                }
            />
            <ChildPortal
                label="Account history"
                tabs={accountTabs(user.id)}
                value={tab}
                onChange={onTabChange}
            />
        </Stack>
    )
}
```

Both tabs read admin-only routes (the accounts' history and the whole log), which is
why the page is for admins. `auditLogParams` (`api/auditLogs.ts:37-46`) drops the blank
filters.

### test/components/admin/UserDetail.test.tsx — new

Mock `../../../api/auditLogs`; `fetchRecordHistoryPage` and `fetchAuditLogPage`
resolve `auditPage([])` (`test/utils/fixtures.ts`). Render with `renderWithProviders`,
`user={plainUser}`, `tab=""`, and `vi.fn()` handlers. Cases:

- The heading is level 1 `user@example.com`, the subtitle `user` shows, Edit calls
  `onEdit`, and there is no Delete button.
- `getByText('Sign-in').parentElement` reads `Sign-inPassword`, or
  `Sign-inNo password` for `{ ...plainUser, has_password: false }`; the Created row
  shows `formatLocalDateTime(plainUser.created_at)`.
- With `tab=""` the History tab is selected and `fetchRecordHistoryPage` is called
  with `('users', 2, 1)`.
- With `tab="activity"` and `fetchAuditLogPage` resolving
  `auditPage([widgetRenamed])` (with no entries, `AuditLogTab.tsx:150-158` renders
  only its empty text), `fetchAuditLogPage` is called with `({ tableName: '',
  changedById: '2', from: '', to: '' }, 1)` and
  `findByRole('columnheader', { name: 'Record' })` resolves.
- Clicking the Activity tab calls `onTabChange` with `activity`.

### test/components/admin/UsersMasterDetail.test.tsx — new

```tsx
vi.mock('../../../api/users')
vi.mock('../../../api/auditLogs')

const newUser: User = {
    ...plainUser,
    id: 3,
    uuid: 'user-uuid-3',
    email: 'new@example.com',
}

/** Render the example on `route`, beside a probe of the router's location. */
const renderAccounts = (route = '/') =>
    renderWithProviders(
        <>
            <UsersMasterDetail />
            <LocationProbe />
        </>,
        { route },
    )

/** Read one of the location probe's outputs. */
const probe = (label: string) => screen.getByLabelText(label).textContent

/** The account count: the one status region the probe's named outputs leave. */
const accountCount = () => screen.getByRole('status', { name: '' })

/** The list row that opens the account with the given email. */
const rowFor = (email: string) => screen.getByRole('button', { name: new RegExp(email) })
```

`beforeEach`: clear mocks, sign in `adminUser` through `useAuthStore.setState`, list
`[adminUser, plainUser]`, and resolve both audit fetches with `auditPage([])`. Two
more helpers keep the cases from repeating blocks, which fallow would flag:
`openAccount(user, email)` clicks the row and awaits the level-1 heading with that
email, and `saveNewAccount(user)` opens New user, fills `Email` (`new@example.com`)
and `Password` (`longenough`) in `findDialog()`, and clicks Save. Cases:

- The list shows both emails, the level-1 heading `Users`, `accountCount()` reading
  `2 users`, and a visible `Select a user to see their details.`; each row's button
  sits in an `li` (`rowFor(email).closest('li')` is not null).
- `openAccount` on `user@example.com`: the probe reads `?user=2` and `PUSH`; that
  row's button has `aria-current="true"`, and the admin's has none.
- `/?user=2&tab=activity` opens that account with the Activity tab selected.
- From `/?user=2`, clicking the Activity tab makes the probe read
  `?user=2&tab=activity` and `REPLACE`.
- `it.each` over `/?user=99` and `/?user=abc`: once the list loads, the empty state is
  visible and `Users` is the only level-1 heading.
- At 375 px, `openAccount` hides the list (`getByText('Users')` is
  `not.toBeVisible()`); Back shows it again, and the probe reads an empty search and
  `PUSH`.
- At 375 px, `/?user=2`: once the heading appears, the detail pane
  (`heading.closest('[tabindex="-1"]')`) has focus, because the record appeared after
  the first render, when the list loaded.
- New user: `usersApi.create` resolves `newUser`, and after the first load
  `usersApi.list` resolves all three; after `saveNewAccount`, the level-1 heading
  `new@example.com` appears, the probe reads `?user=3`, and the dialog closes.
- A failed refetch empties the count: after the first load `usersApi.list` rejects
  with `new Error('Network down')`; `saveNewAccount` invalidates the list, and the
  `alert` shows while `accountCount()` is empty, though the query still holds the
  stale accounts. This is the case that kills dropping `query.isError`.
- Edit: from `/?user=2`, Edit opens `Edit user`; clear `Email`, type
  `renamed@example.com`, and Save; `usersApi.update` is called with `2` and
  `expect.objectContaining({ email: 'renamed@example.com' })`. Do not copy
  `UsersAdmin.test.tsx:143-151`, which fallow would count as a clone.
- A pending list (`new Promise(() => undefined)`) and a rejected one (`new
  Error('Network down')`, shown in an `alert`) both leave `accountCount()` empty.

### pages/Home.tsx — the example for admins, the welcome for everyone else

```tsx
/** @file Landing page: the accounts for an admin, a welcome for everyone else. */

import { Container, Typography } from '@mui/material'

import UsersMasterDetail from '../components/admin/UsersMasterDetail'
import { useAuthStore } from '../store/auth'
import { isAdmin } from '../types/auth'

/**
 * Render the placeholder welcome.
 *
 * @returns The welcome element.
 */
function Welcome() {
    return (
        <Container maxWidth="sm" sx={{ py: 8, textAlign: 'center' }}>
            <Typography variant="h3" component="h1" gutterBottom>
                Hello, World
            </Typography>
            <Typography color="text.secondary">
                Your Flask + React project starts here. Edit{' '}
                <code>src_front/src/pages/Home.tsx</code> to get going.
            </Typography>
        </Container>
    )
}

/**
 * Render the landing page.
 *
 * An admin sees the accounts as a master-detail page, the layout kit's example. The
 * accounts routes are admin-only, so everyone else sees the welcome. A project
 * replaces both with its own landing page.
 *
 * @returns The home page element.
 */
export default function Home() {
    const showAccounts = useAuthStore((s) => s.user !== null && isAdmin(s.user.role))
    return showAccounts ? <UsersMasterDetail /> : <Welcome />
}
```

`test/pages/Home.test.tsx`: mock `../../api/users` (list `[adminUser, plainUser]`).
With `adminUser` signed in, the level-1 heading `Users` and `user@example.com` appear.
`it.each` over `plainUser` and `null`: the heading `Hello, World` shows and
`usersApi.list` is not called.

### test/App.test.tsx — Home now depends on the role

- "renders the shell and the home page at / when signed in" (lines 75-88) and
  "redirects unknown paths to /" (90-96) sign in with `signedIn(plainUser)`; the first
  expects `plainUser.email` in the app bar.
- New case, "shows an admin the accounts on the home page": `signedIn()`, render `/`,
  find the level-1 heading `Users`, and expect `usersApi.list` called once.

### ai/conventions.md — the master-detail convention and the viewport stub

After the `RecordAuditLogTab` bullet (lines 177-181), add:

```markdown
- A page that lists records beside the selected one is a `MasterDetailLayout`
  (`components/layout/`): from `md` up the list and the detail sit side by side, and
  below it one shows at a time, with a Back button, and focus moves to the pane that
  appears. `AppShell` fills the visible viewport and gives `main` a definite height,
  so each pane scrolls on its own under the app bar. `ListPaneHeader` heads the list
  with its title, a count in a polite status region, and an action such as New. The
  detail opens with a `DetailHeader`, lays its sections out in `DetailColumns` (two
  columns from `lg`) and its captioned rows in `LabeledRow`, and shows a record's
  child lists in a `ChildPortal`, tabs that become a select below `sm`. The page keeps
  its UI state in the URL with `useSearchParamWriter`: the selected record with
  `{ push: true }`, so Back returns from a record to the list, and a tab or a filter
  replacing the entry. `components/admin/UsersMasterDetail.tsx`, which an admin sees
  on Home, is the example.
```

Replace the tests bullet (lines 188-193) with:

```markdown
- Tests mirror `src/` under `src/test/`, so `src/components/common/RecordSection.tsx`
  is tested in `test/components/common/RecordSection.test.tsx`. Shared helpers live in
  `test/utils/`: `Providers` and `renderWithProviders` (a query client and a router),
  `FormHarness`, `LocationProbe`, the dialog queries, and the `adminUser` and
  `plainUser` fixtures. `test/globalSetup.ts` pins `TZ` to `America/Los_Angeles`,
  where date-only bugs show, and `test/setup.ts` stubs `IntersectionObserver` and
  `matchMedia`, which jsdom lacks, with `matchMedia` answering as a 1280 px viewport;
  `stubViewportWidth(375)` from `test/utils/viewport.ts` gives a test a phone. jsdom
  applies no media query with a feature, and MUI puts every responsive `sx` value
  behind one, so a layout a test must check at a breakpoint reads it with
  `useMediaQuery(theme.breakpoints.up('md'))`, `theme` coming from `useTheme()`, as
  `MasterDetailLayout` and `ChildPortal` do: the callback form throws without a
  `ThemeProvider`, which tests do not render.
```

### ai/project.md — layout

Lines 32-34 become:

```markdown
    - `components/` - React components; `components/layout/` holds `AppShell.tsx`, the
      shell, and the master-detail layout (`MasterDetailLayout`, `ListPaneHeader`,
      `ChildPortal`); `components/common/` holds the form, record-list, and detail
      kit; and `components/admin/` the admin screens and `UsersMasterDetail`, the
      example an admin sees on Home
```

Line 40 becomes:

```markdown
    - `utils/` - framework-free helpers, such as local-day dates, record counts, and
      account descriptions
```

### README.md — project layout

Lines 224 and 230 of the tree become these (88 and 71 characters):

```text
│       ├── components/  Shell, route guards, error boundaries, layout/, common/, admin/
│       ├── utils/     # Local-day dates, record counts, account labels
```

## Parallelism

Do these first, yourself, before any group starts. Every group's tests load
`test/setup.ts`, so a group would otherwise see the setup change land in the middle of
its own runs:

1. `test/utils/viewport.ts` and the `test/setup.ts` edit.
2. `utils/counts.ts` and its test (`ListPaneHeader` imports it).

Then in parallel:

- **Group A, layout**: `MasterDetailLayout`, `ListPaneHeader`, `ChildPortal`, and their
  tests.
- **Group B, detail**: `DetailHeader`, `DetailColumns`, `LabeledRow`, and their tests.
- **Group C, shared pieces**: the writer's `push` option and its check for a value
  already there, `LocationProbe`, and the writer test; `hooks/users.ts` and its test;
  `utils/users.ts`, its test, and `UsersAdmin.tsx`; `AppShell.tsx` and its test.

Must be sequential, after A, B, and C:

- **Group D, the example**: `UsersMasterDetail.tsx`, `UserDetail.tsx`, `Home.tsx`,
  their tests, and `App.test.tsx`. It imports everything A, B, and C build.
- **Group E, docs**, can run beside D: the names it cites are fixed by this plan.

Each group runs its own tests in one call, as Group A does with:

```bash
npx vitest run test/components/layout/MasterDetailLayout \
  test/components/layout/ListPaneHeader test/components/layout/ChildPortal
```

Each group also mutation-checks its tests on scratch copies, never the real files.
Mutations each group must see killed:

- A: `sideBySide || !showDetail` to `true`; `sideBySide || showDetail` to `true`;
  `up('md')` to `up('lg')` or `up('sm')`; `!sideBySide &&` to `true &&`; dropping
  `if (sideBySide) return` or the `shownBefore` check; swapping `detailRef` and
  `listRef`; `count !== undefined &&` to `true &&`; `component="h1"` to `"h2"`;
  dropping `VISUALLY_HIDDEN`; `down('sm')` to `down('md')`; `?? tabs[0]` to
  `?? tabs[1]`; dropping the `tabs.length === 0` return; dropping `role` or
  `aria-labelledby` on the panel.
- B: `onEdit &&` or `onDelete &&` to `true &&`; dropping the title box's `minWidth` or
  `overflowWrap`.
- C: `{ replace: !push }` to `{ replace: true }`; dropping the writer's check for a
  value already there; dropping `alsoInvalidate`; dropping `100dvh` or the main
  region's `display: 'flex'`.
- D: `{ push: true }` to `{}`; `String(user.id) === selectedId` to `true`;
  `query.isError ? undefined :` dropped; `select(created.id)` dropped; `aria-current`
  dropped; the rows' `ListItem` dropped; `isAdmin(s.user.role)` to `true`.

## No other changes needed

- Backend, migrations, and `api/`: every route exists. Nothing new is audited.
- `RecordSection`, `EntityList`, and the admin Users tab stay as they are.
- `UserFormDialog`, `QueryState`, `useRecordDialogs`, `RecordAuditLogTab`,
  `AuditLogTab`, `hooks/auditLogs.ts`, `utils/dates.ts`: reused unchanged.
- `theme.ts`: MUI's default breakpoints (`sm` 600, `md` 900, `lg` 1200) stay. Tests
  render without the `ThemeProvider`, where `useTheme()` returns MUI's default theme,
  whose breakpoints are the same.
- `package.json`, `vite.config.ts`, `tools.md`, `.fallowrc.json`: no new dependency,
  and the two new icons come from `@mui/icons-material`, already in the `mui` chunk.

## Verification

1. While building, each group runs its targeted tests (Parallelism).
2. At the end, in parallel: `npm run test`, `npm run lint -- --max-warnings=0`, and
   `npm run lint:py`; then `npm run typecheck`, `npm run fallow`, `npm run build`, and
   `npm run lint:md`. All must pass, the suites at 100% coverage.
3. In Chrome, with the dev stack (`npm run docker:up` in the background, then
   `npm run docker:url`). In the scratchpad, run
   `PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 npm i playwright@1.64.1` and a script that
   launches `chromium.launch({ channel: 'chrome' })`, the installed Google Chrome, so
   nothing is downloaded or added to the repository. Sign in as `ADMIN_EMAIL` from
   `.env`, reading the password without printing it. Screenshot each step and read the
   screenshots with the Read tool.
    - 1280×800 at `/`: the list and the empty state side by side, no Back. Open an
      account: the detail beside the list, a two-column Sign-in and Created row (their
      captions share a top edge, since 1280 is above `lg`), tabs, and History. Click
      its row again, then `page.goBack()` once: the empty state returns, so the
      second click pushed nothing.
    - 375×812: only the list. Focus a row and press Enter: only the detail, a Back
      button, a select in place of the tabs, and `document.activeElement` is the
      detail pane. `page.goBack()` returns to the list (the pushed entry); open the
      account again and press Back: the list, with the list pane focused.
    - 375×667 with the account open: the detail pane scrolls on its own
      (`scrollHeight > clientHeight`) while the document does not, and the list pane's
      height equals the main region's.
    - 1280×500 at `/admin/audit`: scroll the window to the end; the last table row
      comes into view, so the fixed-height shell clips nothing on a long page.
    - New user, as `layout-check-<timestamp>@example.com`: the new account opens at
      once. It stays in the dev database; deactivate it afterwards if unwanted.
4. Not checkable here: iOS Safari's toolbars against `100dvh`, which needs an iPhone.
