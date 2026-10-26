# Issue #7: Add admin user management

## Context

The template has `admin` and `user` roles and `admin_required`, but nothing manages
accounts: the README tells the first user to promote themself in the database, and an
account cannot be locked out without deleting it. This ports hukilau's implementation
(issue reference `0698f93`; read at hukilau `origin/staging`, a6cef24, where none of the
user-management files have changed since) and the comment's fold-ins. Nothing exists
yet: no users endpoint or API client, no TanStack Query, no shared form or list
components. `admin_required`, the error envelopes, `paginate_select`, `fetchAll`,
`PaginatedResponse`, and `isAdmin` already exist and are reused.

Read hukilau files with `git -C /Users/chuck/Projects/family/hukilau show
origin/staging:<path>`; its working tree is on another branch.

Decisions made with Chuck on 2026-10-25, beyond the issue text:

- `complete_login()` enforces deactivation: it raises a new `InactiveAccountError`
  (403), so the OAuth callbacks (#29) and passkey sign-in (#32) inherit the check.
- Seed: the structure only (one app context, one commit, one printed line per skip),
  with `_seed_admin` the only step. No `_insert_missing` or `seed_data.py` until a
  project seeds lookup or sample rows; the module docstring says where they go.

Choices this plan makes:

- Every email lookup goes through `find_user_by_email()`. Hukilau's raw
  `filter_by(email=...)` misses a mixed-case `ADMIN_EMAIL` on the second boot, so the
  seed hits the unique constraint and the container stops; in the users service the
  same miss turns a mixed-case duplicate into a 500 instead of a 409.
- The fold-ins with no consumer yet (`useInfiniteList`, `InfiniteScrollSentinel`,
  `useDebouncedValue`, `useSearchParamWriter`, `utils/dates.ts`) ship with tests. Fallow
  declares test files as entry points, so an export a test imports counts as used; #18
  consumes `useSearchParamWriter`.
- Fallow fails on new exports that no module imports, hukilau's exported props
  interfaces included. Export only what another module or a test imports (list in the
  frontend section).
- The UI says "Users" ("New user", "Edit user") where hukilau says "Accounts".
- AppShell nav links get icons and collapse below `sm` as Logout does (hukilau's
  approach): the title plus three labeled buttons overflow a 375px bar.
- Existing tests move into a tree mirroring `src/`, and their per-file `AuthUser`
  fixtures give way to shared ones in `test/utils/fixtures.ts` (each carries
  `is_active: true`). Moved files count as new to fallow's duplication audit, so
  seven copies of one fixture would fail it.
- The users list pages in SQL with `paginate_select`, not hukilau's in-memory
  `paginate_and_dump`.
- Two fixes to the ported code, found while checking it against the installed
  libraries: FormDialog and ConfirmDialog disable their confirming button while
  closing (a double click during the fade-out turned an edit into a create), and the
  generic delete drops the record's detail query before invalidating the list (the
  comment's fix).

## Branch

`issue-7-add-admin-user-management` — already checked out; PR #43 exists.

## Change

**Backend, edit**: `src_back/models/user.py`, `src_back/app.py`,
`src_back/api/__init__.py`, `src_back/api/auth.py`, `src_back/services/auth.py`,
`src_back/services/errors.py`, `src_back/schemas/user.py`, `src_back/seed.py`,
`src_back/tests/{conftest,test_app,test_auth,test_schemas,test_seed}.py`.
**Backend, new**: `src_back/api/users.py`, `src_back/services/users.py`, the
`user_is_active` migration, `src_back/tests/test_users_api.py`,
`src_back/tests/test_errors.py`.
**Config**: `.env.example`, `docker-compose.yml`, `docker/docker-compose.prod.yml`,
`scripts/provision.sh`.
**Frontend**: `package.json`, `package-lock.json`, `vite.config.ts`,
`tsconfig.test.json`, about 25 new source files, edits to `main.tsx`, `App.tsx`,
`theme.ts`, `components/ErrorBoundary.tsx`, `components/layout/AppShell.tsx`,
`types/auth.ts`, and the test tree.
**Docs**: `README.md`, `tools.md`, `ai/project.md`, `ai/conventions.md`,
`ai/domain.md`, `ai/auth.md`.

### src_back/models/user.py — `is_active`

- Line 6: `from sqlalchemy import Boolean, Enum, String, true`.
- `Role` docstring (line 18): "New accounts receive :attr:`user`; an admin promotes them
  through ``PUT /api/v1/users/<id>``."
- `User` docstring (43-50), add: "``is_active`` replaces Flask-Login's
  ``UserMixin.is_active``: a deactivated account keeps the rows that reference it but
  cannot sign in, and :func:`src_back.app.load_user` ends its session on its next
  request."
- After `role` (56-58), as hukilau `src_back/models/user.py:41-43` has it (Ruff does
  not count the trailing pragma toward the line length):

```python
    is_active: Mapped[bool] = mapped_column(  # pyright: ignore[reportIncompatibleMethodOverride]
        Boolean, default=True, server_default=true()
    )
```

### migrations/versions — new `<date>_<rev>_user_is_active.py`

1. `docker compose up -d db`, then `.venv/bin/flask --app src_back.app db upgrade`.
2. `.venv/bin/flask --app src_back.app db migrate -m "user is active"`.
3. Review it: `down_revision = 'e0234c78c7e5'`; upgrade adds
   `sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'),
   nullable=False)` to `users`; downgrade drops it. Give the docstring one sentence:
   existing accounts become active through the server default.
4. `db upgrade`, then `db check` (no new upgrade operations).

### src_back/services/errors.py — four exceptions

Keep `DuplicateRecordError` and `LastSignInMethodError`; add, as in hukilau
`src_back/services/errors.py:8-27`, `RecordInUseError` (its `__init__(message, count)`
stores `self.count`), `ProtectedRecordError` (409), `SelfModificationError` (400), and:

```python
class InactiveAccountError(Exception):
    """A deactivated account tried to sign in (403)."""
```

### src_back/services/auth.py — refuse a deactivated account

`complete_login` (81-93) checks before `login_user`; Flask-Login's `login_user` would
otherwise return `False` silently and the route would still answer 200:

```python
    if not user.is_active:
        raise InactiveAccountError('Account is inactive.')
    login_user(user)
    session.permanent = True
```

Docstring: add a `Raises:` entry and say that every sign-in path inherits the refusal
because it ends here, and that callers verify the credential first, so the refusal
never tells a stranger an address is registered. In `register_user`'s docstring (37-38)
replace "admins are promoted out of band rather than at registration" with "an admin
promotes them on the Users screen".

### src_back/schemas/user.py — admin, update, and registration schemas

Replace the module (module docstring: admin management, registration, sign-in, and
serialization). Hukilau `src_back/schemas/user.py` plus `has_password` and
`RegistrationSchema`:

```python
PASSWORD_RULE = validate.Length(min=8, error='Password must be at least 8 characters.')


class UserSchema(BaseSchema):
    # Docstring: serializes accounts and validates the admin's create payload;
    # password load-only; role and is_active writable because only admins reach
    # the routes that load it (self-registration loads RegistrationSchema);
    # has_password dump-only.
    class Meta(BaseSchema.Meta):
        model = User
        exclude = ('password_hash',)
        dump_only = BaseSchema.AUDIT

    email = fields.Email(required=True)
    password = fields.Str(load_only=True, required=True, validate=PASSWORD_RULE)
    role = fields.Enum(Role, by_value=True, load_default=Role.user)
    is_active = fields.Bool(load_default=True)
    has_password = fields.Boolean(dump_only=True)


class UserUpdateSchema(Schema):
    # Docstring: the admin's update payload; every field optional.
    email = fields.Email()
    password = fields.Str(load_only=True, validate=PASSWORD_RULE)
    role = fields.Enum(Role, by_value=True)
    is_active = fields.Bool()


class RegistrationSchema(Schema):
    # Docstring: self-registration takes only an email and a password; role or
    # is_active in the body is an unknown field, so validation fails with 422
    # and nobody can register as an admin.
    email = fields.Email(required=True)
    password = fields.Str(required=True, load_only=True, validate=PASSWORD_RULE)
```

`LoginSchema` is unchanged. Instances: `user_schema`, `user_update_schema`,
`registration_schema`, `login_schema`.

### src_back/api/auth.py — registration schema and the 403

- Imports: add `registration_schema`, `InactiveAccountError`, and `forbidden`.
- `register` (29): `data = parse_request_json(registration_schema)`; the response
  still dumps with `user_schema`. Docstring: role or is_active in the body answers 422.
- `login` (51-56): after the `unauthorized` return, wrap `complete_login(user)` in
  `try` / `except InactiveAccountError as exc: return forbidden(str(exc))`. Docstring
  `Returns:` adds the 403 and why it comes after the password check.

### src_back/services/users.py — new

Port hukilau `src_back/services/users.py` (create, update, the self-modification rule,
`EMAIL_IN_USE`, `SELF_MODIFICATION`), with two changes:

- `list_users()` becomes `select_users_in_email_order() -> Select[tuple[User]]`,
  returning `select(User).order_by(User.email)`, so the route pages in SQL through
  `paginate_select` (#6) instead of loading every account.
- `_is_email_taken` looks up through `find_user_by_email(email)` from
  `src_back.services.auth`; its docstring says letter case is ignored, as in every
  email comparison.

Functions, not a `CRUDService` subclass: `CRUDService.create` would hand `password` to
the model constructor.

### src_back/api/users.py — new

Port hukilau `src_back/api/users.py`, with `from src_back.auth import current_user`
(typed `User`; `admin_required` guarantees a signed-in caller), `Response` imported
from flask, `-> tuple[Response, int]` on all three handlers, and the list handler
returning `paginate_select(select_users_in_email_order(), user_schema)`.

### `src_back/api/__init__.py` and `src_back/app.py`

- `api/__init__.py`: `from src_back.api.users import bp as users_bp`; add to `__all__`.
- `_register_blueprints` (217-220): import `users_bp` and register it at
  `/api/v1/users`.
- `load_user` (47-57): return `None` when the account is missing or
  `not user.is_active`; docstring: a deactivated account loads as nobody, so its
  session ends on its next request.

### src_back/seed.py — first admin

```python
def seed(app: Flask) -> None:
    with app.app_context():
        _seed_admin()
        db.session.commit()


def _seed_admin() -> None:
    email = os.environ.get('ADMIN_EMAIL', '').strip()
    password = os.environ.get('ADMIN_PASSWORD', '')
    if not email or not password.strip():
        print('Skipping admin seed: ADMIN_EMAIL and ADMIN_PASSWORD are not set.')
        return
    if find_user_by_email(email) is not None:
        print(f'Admin {email} already exists; skipping admin seed.')
        return
    user = User(email=email, role=Role.admin, is_active=True)
    user.set_password(password)
    db.session.add(user)
    db.session.flush()
    print(f'Seeded admin {user.email}.')
```

Module docstring: keep the entrypoint and idempotence paragraph; add that every step
runs in one application context and only flushes, `seed` commits once so a failing
step leaves the database as it was, and a step that skips prints one line saying why.
Then say where a project's next steps go: lookup rows through a step that inserts only
the rows missing by natural key, and development samples through a step that returns
unless `FLASK_ENV` is `development` and the table is empty, with the data in a
`seed_data.py` that never touches the database. `_seed_admin`'s docstring: it never
changes an existing account, so a later `ADMIN_PASSWORD` change resets nobody.

### Configuration

- `.env.example`, after line 12:

```text
# --- Seed -----------------------------------------------------------------------
# src_back/seed.py creates the first admin from these on every backend start. It
# skips when either is blank or the email already has an account, and never changes
# an existing account.
ADMIN_EMAIL=
ADMIN_PASSWORD=
```

- `docker-compose.yml` after line 36 and `docker/docker-compose.prod.yml` after line 25:
  `ADMIN_EMAIL: ${ADMIN_EMAIL:-}` and `ADMIN_PASSWORD: ${ADMIN_PASSWORD:-}`.
- `scripts/provision.sh`: `ADMIN_PASS=$(openssl rand -hex 16)` after `SECRET` (71); in
  the heredoc after the Flask section (after line 99) a `# --- First admin
  (src_back/seed.py) ---` block with `ADMIN_EMAIL=` and `ADMIN_PASSWORD=$ADMIN_PASS`;
  the closing message (129-131) gains "Fill in ADMIN_EMAIL before the first deploy;
  that admin signs in with the generated ADMIN_PASSWORD."

### Backend tests

- `conftest.py`: an `inactive_user` fixture (`inactive@test.com`, `password123`,
  `is_active=False`).
- `test_users_api.py`: port hukilau `src_back/tests/test_users_api.py` (access control,
  list, create, update, self-modification, duplicates, deactivation ending a session)
  with type annotations, `persist()` in `_persist_user`, and the fresh-context helper
  `ai/domain.md` describes. Add: a create and an update whose email differs only in
  case from another account answer 409; a mixed-case create stores the email
  normalized.
- `test_auth.py`: an inactive account with the right password gets 403
  `Account is inactive.`, with a wrong one 401; `complete_login` raises
  `InactiveAccountError` and leaves `flask_login.current_user` anonymous; register
  with `role` or `is_active` answers 422 and creates no row (extend
  `test_register_cannot_choose_a_role`, 106-111); register creates an active `user`.
- `test_app.py`: `load_user` returns `None` for `inactive_user`.
- `test_schemas.py`: the dump field set gains `is_active`; `user_schema.load` of email
  and password returns `role=Role.user` and `is_active=True`; the role and audit
  rejection test (50-56) splits: `id` still fails on `user_schema`, while `role` and
  `is_active` fail on `registration_schema`; `user_update_schema.load({}) == {}` and
  it rejects a short password; `registration_schema` rejects a short password and a
  bad email.
- `test_seed.py`: replace. An autouse fixture deletes `ADMIN_EMAIL` and
  `ADMIN_PASSWORD` (`load_dotenv()` runs at import); parametrized blank and
  whitespace cases create nothing and print the skip line; a padded mixed-case email
  seeds a normalized active admin whose password checks; an existing account under
  the same email in another case keeps its role and password; a second run changes
  nothing.
- `test_errors.py`: `RecordInUseError` keeps its message and `count`.

### Frontend dependencies and config

- `npm install @tanstack/react-query@^5.104.1` (hukilau's range; no devtools).
- `vite.config.ts`: `'@tanstack': 'react'` in `VENDOR_CHUNKS` (5-18), since the
  provider loads at startup; `globalSetup: './src/test/globalSetup.ts'` in `test`
  (82-85).
- `tsconfig.test.json`: `"types": ["vitest/globals", "@testing-library/jest-dom",
  "node"]`, so `process.env` type-checks in `globalSetup.ts`.

### Frontend foundation

Port each file from hukilau `src_front/src/` unchanged unless noted. Fallow fails on a new
export nothing imports, so drop `export` from `FormTextFieldProps`, `SelectOption`,
`FormSelectFieldProps`, `FormSwitchFieldProps`, `QueryLike`, `QueryStateProps`,
`RecordMutations`, `RecordSectionProps`, `InfiniteScrollSentinelProps`,
`UseInfiniteListOptions`, and `UserFormValues`. Keep `EntityAction` (RecordSection
imports it), `RecordDialogProps` (UserFormDialog), `ResourceApi` (hooks/resources),
and `FormDialogProps`, `ConfirmDialogProps`, and `EntityListProps`, which the ported
tests import. Run `npm run fallow` after this batch and drop any other export it
reports.

- `main.tsx`: `const queryClient = new QueryClient()` and a `QueryClientProvider` around
  `BrowserRouter` (hukilau `main.tsx:13,23-27`); the `@file` line says it mounts the app
  with its providers.
- `hooks/useSessionQueryCache.ts`: verbatim; `App.tsx` calls it.
- `api/resources.ts`: only `ResourceApi` and `resource()` (hukilau lines 15-39), both
  exported; no resource instances.
- `api/users.ts` (new): `export const usersApi = resource<User, UserPayload>('/v1/users')`,
  its JSDoc noting the server has no delete route.
- `hooks/resources.ts`: only `useResourceMutations` (hukilau 68-103), exported. Its
  `remove` folds in the comment's detail-cache fix. A detail query's key is
  `[...key, id]`, which TanStack's prefix match would refetch when the list is
  invalidated, showing the deleted record from cache through the retries. So the
  detail query is dropped first:
  `onSuccess: (_data, id) => { queryClient.removeQueries({ queryKey: [...key, id] });
  invalidate() }`.
- `hooks/users.ts` (new): a private `USERS_KEY = ['users'] as const`, `useUsers()`, and
  `useUserMutations()`, which returns `{ create, update }` from `useResourceMutations`
  so `RecordSection` offers no Delete.
- `hooks/useRecordDialogs.ts`; `components/common/FormTextField.tsx`,
  `FormSelectField.tsx`, `FormSwitchField.tsx`, `EntityList.tsx`, `QueryState.tsx`:
  verbatim apart from the dropped exports.
- `components/common/FormDialog.tsx` and `ConfirmDialog.tsx`: hukilau's, with the
  confirming button also disabled while the dialog is closing: `disabled={pending ||
  !open}` in ConfirmDialog, and in FormDialog the body receives `open` (drop it from
  the `Omit`) and uses `isSubmitting || !open`. MUI keeps a closing dialog clickable
  through its fade-out. A second Save in that window reaches `submit` after `editing`
  is cleared and creates a record with the payload of the one just edited, a bug
  hukilau has.
- `components/common/RecordSection.tsx`: hukilau's file with the delete side optional.
  The confirmation moves into a local `RecordDeleteDialog`, which keeps
  `useRecordHandlers` under 50 lines and lets TypeScript narrow `remove` without an
  assertion. A row offers Delete only with `mutations.remove`, and no confirmation
  renders without it. The design below compiles against the template's TypeScript 6:

```tsx
/** A mutation that deletes a record by id, such as a TanStack `useMutation` result. */
interface RemoveMutation {
    mutateAsync: (id: number) => Promise<unknown>
}

/** The mutations a record list drives; without `remove`, no row offers Delete. */
interface RecordMutations<T, P> {
    create: { mutateAsync: (payload: P) => Promise<T> }
    update: { mutateAsync: (args: { id: number; payload: P }) => Promise<T> }
    remove?: RemoveMutation
}

// RecordSectionProps: hukilau's, with canDelete, deleteTitle (default
// 'Delete record'), and deleteMessage (default: a permanence warning) optional.

/** Props accepted by {@link RecordDeleteDialog}. */
interface RecordDeleteDialogProps<T extends { id: number }> {
    item: T | null
    remove: RemoveMutation
    title?: string
    message?: (item: T) => string
    onClose: () => void
}

/**
 * Warn that a delete is permanent, for lists that pass no message of their own.
 *
 * @returns The warning.
 */
const permanenceWarning = () => 'This cannot be undone.'

/**
 * Ask before deleting the selected record, then delete it and close.
 *
 * @param props - The component props.
 * @returns The confirmation, open while a record is selected.
 */
function RecordDeleteDialog<T extends { id: number }>(
    props: RecordDeleteDialogProps<T>,
) {
    const {
        item,
        remove,
        title = 'Delete record',
        message = permanenceWarning,
        onClose,
    } = props

    /** Delete the selected record, then close the confirmation. */
    const confirm = async () => {
        // Delete is clickable only while open, and the dialog is open only with an item.
        await remove.mutateAsync(item!.id)
        onClose()
    }

    return (
        <ConfirmDialog
            open={item !== null}
            title={title}
            message={item ? message(item) : ''}
            onCancel={onClose}
            onConfirm={confirm}
        />
    )
}
```

  In `useRecordHandlers`, `confirmDelete` goes away and the Delete action is pushed
  when `mutations.remove && (canDelete?.(item) ?? true)`. `RecordSection` renders
  `{mutations.remove && <RecordDeleteDialog item={dialogs.deleting}
  remove={mutations.remove} title={deleteTitle} message={deleteMessage}
  onClose={dialogs.close} />}` after the form dialog.

- Fold-ins: `hooks/useInfiniteList.ts`, `components/common/InfiniteScrollSentinel.tsx`,
  `hooks/useDebouncedValue.ts`, and `utils/dates.ts`, verbatim. The new
  `hooks/useSearchParamWriter.ts` exports the function hukilau keeps private in
  `hooks/usePeopleFilters.ts:39-55`, with a `@file` block and JSDoc (writes one query
  parameter, deletes it when the value is empty, replaces the history entry).
- `test/globalSetup.ts`: hukilau's (`process.env.TZ = 'America/Los_Angeles'`).
  `test/setup.ts`: hukilau's, which adds the inert `IntersectionObserver` stub.
- `theme.ts`: keep phone-width inputs at 16px so iOS Safari does not zoom on focus.
  Object form, so there is no callback to cover:

```ts
const { breakpoints } = createTheme()

/** The application theme: MUI's defaults in light mode, inputs 16px below `sm`. */
export const theme = createTheme({
    palette: { mode: 'light' },
    components: {
        MuiInputBase: {
            styleOverrides: {
                // iOS Safari zooms the page when a focused input's text is under 16px.
                input: { [breakpoints.down('sm')]: { fontSize: 16 } },
            },
        },
    },
})
```

- `components/ErrorBoundary.tsx`: an optional `resetKey` prop ("Clears a caught error
  when it changes, such as the routed page's pathname") and the method below.
  React Router renders sibling routes at one tree position without keys, so they share
  one boundary instance, and without a reset an error would stay on screen after
  navigating away. The `prevState.hasError` guard (react-error-boundary's) stops an
  update that both changes the key and throws from rendering the failure twice:

```tsx
    /**
     * Leave the error state when the reset key changes after an error was shown.
     *
     * @param prevProps - The props of the previous render.
     * @param prevState - The state of the previous render.
     */
    componentDidUpdate(prevProps: Props, prevState: State) {
        if (prevState.hasError && prevProps.resetKey !== this.props.resetKey) {
            this.setState({ hasError: false })
        }
    }
```

- `components/RouteErrorBoundary.tsx` (new): a pathless layout route rendering
  `<ErrorBoundary resetKey={useLocation().pathname}><Outlet /></ErrorBoundary>`.
  One instance serves every page beneath it, so pages added later are covered too;
  inside `AppShell` the app bar survives a failing page, and inside the Suspense
  boundaries it also catches a failed lazy chunk. If fallow reports
  `componentDidUpdate`, add `usedClassMembers: [{ "extends": "Component", "members":
  ["componentDidUpdate"] }]` to `.fallowrc.json`.

### Admin screen

- `types/auth.ts`: `is_active: boolean` after `has_password`, documented as false once
  an admin deactivates the account.
- `types/users.ts`, `schemas/user.ts`: hukilau's, verbatim (`UserFormValues` unexported).
- `components/admin/UserFormDialog.tsx`: hukilau's, titled "New user" and "Edit user".
  On edit, the password helper text reads "Leave blank to keep the current password."
  when `item.has_password`, otherwise "This account has no password; leave blank to
  keep it that way."
- `components/admin/UsersAdmin.tsx`: hukilau's, using `useUsers` and `useUserMutations`
  from `hooks/users`; title "Users", add label "New user", empty text "No users yet.";
  no `canDelete`, `deleteTitle`, or `deleteMessage`.
- `components/AdminRoute.tsx`: hukilau's; non-admins go to `/`.
- `pages/AdminPage.tsx`: one `SECTIONS` array builds both the tabs and the descendant
  routes. Links and redirects are absolute: under a splat route React Router resolves
  a relative path against the whole URL, so `users` from `/admin/nope` means
  `/admin/nope/users` and would redirect forever. The selected tab comes from
  `useParams()['*']`, and `false`, MUI's "no tab selected", covers the empty segment
  before the index redirect lands, so `Tabs` never warns:

```tsx
/** @file The admin screen: one tab and one child route per section, from one list. */

import { Box, Container, Tab, Tabs } from '@mui/material'
import type { ReactNode } from 'react'
import { Link, Navigate, Route, Routes, useParams } from 'react-router-dom'

import UsersAdmin from '../components/admin/UsersAdmin'

/** One admin section: its route segment, its tab label, and its content. */
interface AdminSection {
    path: string
    label: string
    element: ReactNode
}

/** Where `App.tsx` mounts this page, as `/admin/*`. */
const ADMIN_BASE = '/admin'

/** Every admin section, in tab order; `/admin` and unknown paths land on the first. */
const SECTIONS: AdminSection[] = [
    { path: 'users', label: 'Users', element: <UsersAdmin /> },
]

/** The first section's absolute path, the target of both redirects. */
const LANDING_PATH = `${ADMIN_BASE}/${SECTIONS[0].path}`

/**
 * Render the section tabs and, beneath them, the section the URL names.
 *
 * (Docstring: the sections are descendant routes of `/admin/*`; why links and
 * redirects are absolute; why an unknown segment selects no tab.)
 *
 * @returns The page element.
 */
export default function AdminPage() {
    const segment = useParams()['*']?.split('/')[0]
    const selected = SECTIONS.find((section) => section.path === segment)?.path ?? false
    return (
        <Container maxWidth="md" sx={{ py: 2 }}>
            <Tabs
                value={selected}
                variant="scrollable"
                scrollButtons="auto"
                sx={{ mb: 2 }}
            >
                {SECTIONS.map((section) => (
                    <Tab
                        key={section.path}
                        value={section.path}
                        label={section.label}
                        component={Link}
                        to={`${ADMIN_BASE}/${section.path}`}
                    />
                ))}
            </Tabs>
            <Box>
                <Routes>
                    <Route index element={<Navigate to={LANDING_PATH} replace />} />
                    {SECTIONS.map((section) => (
                        <Route
                            key={section.path}
                            path={section.path}
                            element={section.element}
                        />
                    ))}
                    <Route path="*" element={<Navigate to={LANDING_PATH} replace />} />
                </Routes>
            </Box>
        </Container>
    )
}
```

  A later section with routes of its own gets `path: '<segment>/*'`.

- `App.tsx`: call `useSessionQueryCache()` first; add
  `const AdminPage = lazy(() => import('./pages/AdminPage'))`; mount
  `RouteErrorBoundary` as a pathless layout route twice, once around the sign-in pages
  and once inside `AppShell`; update the docstring:

```tsx
            <Routes>
                <Route element={<RouteErrorBoundary />}>
                    <Route path="/login" element={<Login />} />
                    <Route path="/register" element={<Register />} />
                </Route>
                <Route element={<ProtectedRoute />}>
                    <Route element={<AppShell />}>
                        <Route element={<RouteErrorBoundary />}>
                            <Route index element={<Home />} />
                            <Route element={<AdminRoute />}>
                                <Route path="/admin/*" element={<AdminPage />} />
                            </Route>
                        </Route>
                    </Route>
                </Route>
                <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
```

- `components/layout/AppShell.tsx`: hukilau's `NavLinks`, `UserMenu`, and the two
  `COLLAPSIBLE_*` sx constants, with `NAV_LINKS` of Home (`HomeIcon`, `/`) and Admin
  (`AdminPanelSettingsIcon`, `/admin`, `adminOnly`). A link is current on its own path
  or below it (`pathname === to || pathname.startsWith(`${to}/`)`, so Home is current
  only on `/`). The email hides below `sm`. Keep the template's title, its
  `minHeight: '100vh'` layout, and the `Suspense` around `Outlet`; hukilau's
  fixed-height layout belongs to #18.

### Frontend tests

Move first, so new tests land in the new layout (`git mv`, one more `../` per level in
imports and `vi.mock` paths):

| From `test/` | To `test/` |
| --- | --- |
| `authApi.test.ts` | `api/auth.test.ts` |
| `client.test.ts` | `api/client.test.ts` |
| `ErrorBoundary.test.tsx`, `ProtectedRoute.test.tsx` | `components/` |
| `AppShell.test.tsx` | `components/layout/` |
| `useApiError.test.tsx` | `hooks/` |
| `Login.test.tsx`, `Register.test.tsx` | `pages/` |
| `store.test.ts` | `store/auth.test.ts` |
| `types.test.ts` | `types/auth.test.ts` |

`App.test.tsx`, `theme.test.ts`, `setup.ts`, and `globalSetup.ts` stay at the root.

New shared helpers in `test/utils/`, from hukilau's: `Providers.tsx` (creates its
`QueryClient` once with `useState`, retries off, `gcTime: 0`, plus a `MemoryRouter`),
`renderWithProviders.tsx` (catch routes for `/` and `/login`, not `/people`),
`FormHarness.tsx`, `dialogs.ts`, `dialogQueries.ts`, and `fixtures.ts` with `adminUser`
and `plainUser` (`has_password: true`, `is_active: true`). Every existing test imports
these instead of declaring its own `AuthUser`; keep the assertions on whatever email
or role each test checks.

Changed tests:

- `App.test.tsx`: render `<Providers route={path}><App /></Providers>` instead of the
  bare `MemoryRouter` (`useQueryClient` throws without a provider); an admin at
  `/admin` reaches the Users tab; a non-admin at `/admin` lands on Home.
- `components/layout/AppShell.test.tsx`: Admin link only for an admin; `/admin/users`
  marks Admin current and not Home; every button keeps its accessible name.
- `components/ErrorBoundary.test.tsx`: keep the three tests; add an error then the same
  key (fallback stays), an error then a new key with a fixed child (children render),
  and a fine render on `/a` then a throwing child on `/b` (fallback; covers the guard).
- `theme.test.ts`: the `MuiInputBase` override sets 16px below `sm`.

New tests (ported where hukilau has one):

- `api/resources.test.ts` (each `resource()` method hits the right path with the mocked
  client) and `api/users.test.ts` (`usersApi` targets `/v1/users`).
- `hooks/resources.test.tsx` (each mutation invalidates its key and every extra key;
  `remove` drops `[...key, id]` before invalidating),
  `hooks/users.test.tsx` (`useUsers` loads, `useUserMutations` has no `remove`),
  `hooks/useSessionQueryCache.test.tsx` (hukilau's `test/useSessionQueryCache.test.tsx`),
  `hooks/useRecordDialogs.test.ts` and `hooks/useDebouncedValue.test.tsx` (the two
  cases in hukilau's `test/hooks/localStateHooks.test.tsx`),
  `hooks/useInfiniteList.test.tsx` (modeled on ranch-tracker
  `src_front/src/tests/hooks/useInfiniteList.test.tsx`, plus `lastLoadedPageTotal`),
  `hooks/useSearchParamWriter.test.tsx` (sets, deletes on empty, replaces history).
- `components/common/*.test.tsx` for FormDialog, FormTextField, FormSelectField,
  FormSwitchField, ConfirmDialog, EntityList, QueryState, InfiniteScrollSentinel
  (hukilau's), and RecordSection (new), whose four cases hit every branch:
    - without `remove`: rows offer only Edit, a `canDelete` spy is never called, and
      Add and Edit each submit (create, then update with `{ id, payload }`) and close;
    - with `remove` and no delete props: every row offers Delete, the confirmation
      reads "Delete record" and "This cannot be undone.", and confirming calls
      `remove.mutateAsync(id)` and closes;
    - `canDelete` false for one row, with a custom title and message: that row has no
      Delete, the custom text shows, and Cancel never calls `remove`;
    - `remove` rejects: the alert shows and the dialog stays open.
- `components/AdminRoute.test.tsx`; `components/RouteErrorBoundary.test.tsx`: a
  `MemoryRouter` with a `Link` outside `Routes` and the layout route over `/boom`
  (throws) and `/fine`; the fallback shows on `/boom` while the link stays, clears on
  `/fine`, and returns on going back. Reuse the existing `console.error` spy.
- `components/admin/UsersAdmin.test.tsx` (hukilau's, mocking `../../../api/users`, with
  the new labels, plus the passwordless helper text); `pages/AdminPage.test.tsx`
  (mounted at `path="/admin/*"` with UsersAdmin mocked: `/admin`, `/admin/nope`, and
  `/admin/users/extra` redirect to `/admin/users`, whose tab has the right `href` and
  `aria-selected`); `schemas/user.test.ts`; `utils/dates.test.ts` (hukilau's; it
  needs the `TZ` pin).

### Docs

- `README.md`: stack table (14) adds TanStack Query; the quick start (60-62) sets
  `ADMIN_EMAIL` and `ADMIN_PASSWORD` in `.env` and runs
  `.venv/bin/python -m src_back.seed` after `db upgrade`, replacing "Promote it to
  `admin` in the database"; line 35's test path becomes
  `src_front/src/test/components/layout/AppShell.test.tsx`; the project layout
  (150-180) lists `api/` users, `components/common` and `admin`, `schemas/`, `utils/`,
  `pages/` Admin, `test/` mirroring `src/`.
- `tools.md`: a TanStack Query entry under Frontend runtime libraries; update the
  `@mui/icons-material` (115-116), React Hook Form, and Zod (125-130) entries for the
  admin forms; `@types/node` (153-155) now also serves `test/globalSetup.ts`.
- `ai/project.md`: the new structure (`services/users.py`, `components/common/`,
  `components/admin/`, `schemas/`, `utils/`, `test/utils/`), and in Environment that
  the seed creates the first admin from `ADMIN_EMAIL` and `ADMIN_PASSWORD`.
- `ai/conventions.md`: the exception-to-status mapping (`DuplicateRecordError`,
  `RecordInUseError`, `ProtectedRecordError`, `LastSignInMethodError` 409 through
  `conflict()`; `SelfModificationError` 400 through `bad_request()`;
  `InactiveAccountError` 403 through `forbidden()`); inactive accounts; schemas that
  trim strings do it in `@pre_load` (the generated `Length` validators read the raw
  value); `AdminRoute`; TanStack Query hooks per resource, the cache cleared on an
  account change, and a detail query keyed `[...listKey, id]`, which a delete removes
  with `removeQueries` before invalidating the list; `FormDialog` and `RecordSection`;
  `RouteErrorBoundary` as a layout route; tests mirror `src/`, shared helpers in
  `test/utils/`, `TZ` pinned.
- `ai/domain.md`: Accounts gains admin user management and deactivation; fixtures
  gain `inactive_user`.
- `ai/auth.md`: `complete_login` refuses a deactivated account with
  `InactiveAccountError`, which every caller maps to 403, and checks after the
  credential. A new account must be committed (or given `is_active=True`) before
  `complete_login`, because the column default applies only at INSERT and an unsaved
  `User` reads `is_active` as `None`; #29 and #32 create accounts this way.
  Reactivating an account revives its old sessions within their lifetime, since
  Flask-Login keeps the id in the cookie. The first admin comes from the seed.

## Parallelism

The backend and frontend tracks share only the API contract and never wait on each
other. The batches run in order; the items inside a batch can be done in parallel.

1. One worker, first, because it touches the lockfile and shared config: the
   dependency, `vite.config.ts`, `tsconfig.test.json`, `test/globalSetup.ts`, and the
   `IntersectionObserver` stub.
2. In parallel:
    - the model, then the migration, in that order (autogenerate reads the model);
    - `services/errors.py`;
    - the configuration files;
    - one worker for the test move, `is_active` on `AuthUser`, and the shared
      `test/utils/` helpers (`tsc -b` checks the tests too).
3. In parallel:
    - backend A: `schemas/user.py`, then `complete_login`, `/register` and `/login`,
      `load_user`, and their tests;
    - backend B: `services/users.py`, `_seed_admin`, `test_seed.py`;
    - frontend, one worker per kit: forms (FormDialog and fields); lists
      (ConfirmDialog, EntityList, QueryState, useRecordDialogs, RecordSection); server
      state (resources, `main.tsx`, useSessionQueryCache); standalone (infinite list,
      debounce, search-param writer, dates); shell (both error boundaries, the theme
      rule, AppShell). Nobody edits `App.tsx` yet.
4. In parallel: `api/users.py` with the blueprint and `test_users_api.py`; the admin
   screen (types, `schemas/user.ts`, `api/users.ts`, `hooks/users.ts`, the dialogs,
   AdminRoute, AdminPage) with the single `App.tsx` edit and its tests.
5. In order: the docs, then the full checks and the Docker run.

Per batch, run its tests in one invocation:
`.venv/bin/python -m pytest <files> --no-cov` or `npx vitest run <files>`.

## No other changes needed

- `admin_required`, `conflict`, `bad_request`, `forbidden`, `dump_or_404`,
  `paginate_select`, and `parse_request_json` exist in `src_back/utils.py`.
- `register_user` already raises `DuplicateRecordError` (#28), which the issue lists
  as a change.
- The issue names `src_back/models.py`; the model now lives in
  `src_back/models/user.py`.
- `docker/entrypoint.sh` already runs the seed on every start.
- The Login page already shows a server error's text, so the 403 needs no new code.
- The client's 401 interceptor already clears the store, so a deactivated user's next
  request signs them out in the browser.
- `fetchAll`, `PaginatedResponse`, `isAdmin`, and `useApiError` exist.
- Register, Home, and the Login page's Register link stay: the template keeps open
  registration beside user management, where hukilau removed it.

## Verification

1. Checks, run in parallel: `npm run test`, `npm run lint`, `npm run lint:py`, then
   `npm run lint:md`, `npm run typecheck`, `npm run fallow`, `npm run build`. Both
   suites stay at 100%.
2. Migrations on a fresh database, without touching the dev data:
   `docker compose exec -T db createdb -U app fresh_check`, then with
   `DATABASE_URL=postgresql://app:app@localhost:$DB_PORT/fresh_check` run
   `.venv/bin/flask --app src_back.app db upgrade`, `db check`, `db downgrade -1`, and
   `db upgrade` (`DB_PORT` is in `.env`); finally
   `docker compose exec -T db dropdb -U app fresh_check`.
3. End to end: set `ADMIN_EMAIL=admin@example.com` and `ADMIN_PASSWORD=adminpass123`
   in `.env`, run `npm run docker:up:build -- -d` (the image bakes in the source and
   the new dependency), and confirm `Seeded admin admin@example.com.` in
   `docker compose logs backend`. Against `http://localhost:$BACKEND_PORT`, with
   cookie jars in the scratchpad:
    - the admin logs in (200) and `POST /api/v1/users` creates `temp@example.com` (201);
    - `temp` logs in with its own jar (200);
    - the admin `PUT`s `{"is_active": false}` on `temp` (200);
    - `temp`'s `GET /api/v1/auth/me` answers 401 and a fresh login 403
      `{"error": "Account is inactive."}`;
    - the admin `PUT`s `{"role": "user"}` and `{"is_active": false}` on itself (400 each);
    - `POST /api/v1/auth/register` with `"role": "admin"` answers 422 and the users
      total is unchanged; without it, 201 with `role` `user` and `is_active` true.
4. Restart with `ADMIN_EMAIL=Admin@Example.com`: the backend logs that the admin already
   exists and stays up, rather than failing on the unique constraint.
5. In the browser: the admin sees Admin, creates and deactivates a user on the Users
   tab, and cannot change their own role or active switch; a non-admin opening `/admin`
   lands on Home; at 375px the app bar fits, with icon-only buttons and no email.
6. Restore `.env` afterwards if the admin variables should not stay.
