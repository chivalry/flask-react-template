# Conventions

## Coverage

Both suites require 100% coverage: `--cov-fail-under=100` in `pyproject.toml` and the
four Vitest thresholds in `vite.config.ts`. Coverage includes every source file, so an
untested module fails the build instead of being invisible.

## Backend

Request flow:

```text
API handler -> Service -> Model -> Marshmallow schema -> jsonify()
```

- Blueprints are registered in `app.py`; each domain has one file in `src_back/api/`.
- Handlers stay thin: `parse_request_json(schema)` validates the body (422 on
  failure), a service does the work, and `jsonify(schema.dump(...))`, `dump_or_404`,
  `paginate_and_dump` (slices a loaded list), or `paginate_select` (applies `LIMIT`
  and `OFFSET` in SQL with a count subquery, for tables too large to load whole)
  builds the response.
- `parse_id_list(name)` reads a query parameter such as `?ids=3,1,2` and
  `parse_query_date(name)` a strict `YYYY-MM-DD` date; both raise `ValueError`, which
  the handler answers with `bad_request(str(exc))`.
- Services in `src_back/services/` own business logic. Reuse `CRUDService` for
  top-level resources and `ChildRecordService` for nested ones. Its
  `get_for_parent()` is how nested routes validate parent ownership before mutating;
  `require_parent()` in `utils.py` answers 404 when the parent is missing, and
  `create()` and `update()` keep the URL's parent id authoritative over any parent id
  in the body.
- A service that keeps names unique calls `require_unique_name()` from
  `services/base.py` in `create` and `update`. It compares names with straight and
  curly quotes treated alike but case still counting, and raises `DuplicateRecordError`
  from `services/errors.py`, which the handler answers with `conflict(str(exc))`.
- A service opts into the audit log (`AuditLog`, `services/audit_log.py`) by passing
  `audit_fields` to `CRUDService` or `ChildRecordService`, and `label_field` when its
  records are not named by `name` (`None` for no label). `create` then logs the new
  record's audited fields, `update` the ones it changed (`{field: {old, new}}`, and
  nothing when none did), and `delete` the record's fields after `before_delete`, each
  before the method's commit, so the entry and the change are saved together. The
  actor is the signed-in account, `None` outside a request. A hand-written service
  builds an `AuditTrail` and calls its `log_*` methods before committing, as
  `services/users.py` does with `USER_AUDIT_TRAIL`, and records a secret, such as a
  password, only as `MASKED_VALUE`. Building a trail registers its table, so one
  record's history (`GET /api/v1/audit-logs`) is served only for audited tables.
  `audit_admin_only=True` on a generic service, or `admin_only=True` on a trail, keeps
  a table's history from non-admins, as for accounts, and no later trail can undo it.
  A child record's entries belong to its own table, not its parent's.
- Services raise the exceptions in `services/errors.py`, and the handler catches each
  one and answers with its envelope from `utils.py`: `DuplicateRecordError`,
  `RecordInUseError`, `ProtectedRecordError`, and `LastSignInMethodError` with
  `conflict(str(exc))` (409), `SelfModificationError` with `bad_request(str(exc))`
  (400), and `InactiveAccountError` with `forbidden(str(exc))` (403).
- A service removes a stored file only after the commit that stops referencing it,
  through `delete_upload()` in `utils.py`, which ignores a file that is already gone:
  in `after_delete` for a deleted record, and after its own commit when an update
  replaces the file. A failed commit then leaves the row and its file in place.
- Schemas extend `BaseSchema` (marshmallow-sqlalchemy auto schema with
  `load_instance = False`), set `Meta.model`, and mark `BaseSchema.AUDIT` dump-only.
  Auto schemas omit foreign-key columns; a child schema that accepts the parent id
  in the body sets `include_fk = True`. A schema that accepts a list of ids checks it
  in a `@validates` method with `validate_ids_exist(model, ids, label)`, one `COUNT`
  query, so an unknown id fails with a 422. A schema that trims strings does it in a
  `@pre_load` hook, not `@post_load`: the `Length` validators generated from the
  columns run on the raw value, so a post-load trim still rejects a padded value of
  the maximum length. Every `DateTime` column serializes through `UTCDateTime`, in
  UTC with an explicit offset: SQLite returns datetimes without one, and a browser
  reads such a string as local time. A datetime field declared by hand uses
  `UTCDateTime` too.
- Auth is a Flask-Login session cookie. Every sign-in ends in `complete_login(user)`
  from `services/auth.py`, the only `login_user` call, so a new way to sign in (an
  OAuth callback, a passkey check) calls it too. It marks the session permanent, so
  the cookie carries an expiry and survives a browser restart, and Flask re-sends it
  with a fresh expiry on every response: a sign-in ends at logout or after
  `SESSION_LIFETIME_DAYS` (30, in `app.py`) without a request. Protect routes with
  `@login_required` or `@admin_required` (401 for anonymous callers, 403 for non-admins).
  Routes behind `@login_required` import `current_user` from `src_back/auth.py`, where
  it is typed as `User`; code that checks `is_authenticated` itself, such as
  `admin_required`, keeps Flask-Login's.
- Every POST, PUT, PATCH, or DELETE to `/api` or `/uploads` must carry
  `X-Requested-With: XMLHttpRequest`, which the axios client sends on every request;
  `_require_requested_with_header` in `app.py` answers any other with 403. It is CSRF
  defense in depth. SameSite cookies keep other sites' requests from carrying the
  session, but a sibling subdomain counts as the same site, and an older browser may
  ignore SameSite. A form cannot set a custom header, and a script on another origin
  cannot send one without a CORS preflight, which only the origins in
  `CORS_ALLOWED_ORIGINS` pass: production sets it to the site's own origin, while
  development's `*` passes every origin. A route that must accept a cross-site POST,
  such as Sign in with Apple's `form_post` callback (#30), must be exempted in that
  hook and check its own `state` instead.
- Accounts are deactivated, never deleted, so the rows that reference them stay
  intact. `complete_login` refuses a deactivated account with `InactiveAccountError`,
  and every caller checks the credential first, so the 403 never tells a stranger that
  an address is registered. A deactivated account's session ends on its next request:
  `load_user` in `app.py` loads it as nobody, and Flask-Login's `is_authenticated`
  follows `is_active` as well. An admin cannot demote or deactivate themself
  (`SelfModificationError`), so an active admin always remains.
- `User` stores every email through `normalize_email()` in `models/user.py` (trimmed
  and lowercased), however the account is created or edited, and lookups go through
  `find_user_by_email()` in `services/auth.py`, so letter case never tells two
  accounts apart. Compare emails no other way.
- `app.config['PUBLIC_BASE_URL']` is the only source of the public origin. Build OAuth
  redirect URIs and the WebAuthn origin from it, never from the request: there is no
  `ProxyFix`, so the request does not know the public origin. Development and testing
  default it to `http://localhost:$FRONTEND_PORT`; elsewhere it is `None` when unset,
  and the features that need it stay off. `ai/auth.md` has the details.
- Every function and class has a Google-style docstring, and `pydoclint` checks that
  arguments and returns match it. Functions stay under 50 physical lines
  (`scripts/check_function_length.py`). `basedpyright` runs in standard mode.
- Python uses single quotes (Ruff format) and a line length of 90. Ruff also enforces
  `ANN` (every parameter and return is annotated; `*args: Any` and `**kwargs: Any`
  are allowed on pass-through wrappers), `FBT` (boolean parameters are keyword-only),
  `PTH` (pathlib instead of `os.path`), and `SIM`.
- Ruff targets Python 3.12, matching Docker, CI, and the type checker. This is a
  project-specific exception to the shared `py311` standard; a newer local venv
  does not raise the deployment baseline.

## API Responses

- All endpoints live under `/api`; versioned resources under `/api/v1/`.
- `200` for GET and PUT, `201` for POST create, `204` for DELETE.
- Errors are `{"error": "message"}` with `400`, `401`, `403`, `404`, `409`, `413`,
  `422`, `429`, or `500`. Validation failures are `422`. Host nginx answers throttled
  sign-in POSTs with `429` (`ai/auth.md`).
- Paginated lists are `{"items": [...], "total", "page", "pages", "per_page"}`, with
  `per_page` capped at 100.
- Image uploads go through `validate_image_file()`; stored files are served from
  `/uploads/<filename>` to signed-in users only; bodies over 25 MB return `413`.

## Frontend

- The axios client (`api/client.ts`) uses `baseURL: '/api'`, `withCredentials`, and the
  `X-Requested-With: XMLHttpRequest` header that the backend requires on every request
  that changes data. Its interceptors copy the server's `error` text onto
  `error.message` and notify the auth store on a 401.
- The Zustand auth store holds the signed-in user. `fetchMe()` runs once on mount and
  `ProtectedRoute` waits for it; login and register store the user from their own
  response, as an admin's edit of their own account does from the update's, and a
  `/me` response that lands after a sign-in or sign-out is discarded as stale. Only a
  401 from `/me` ends the session; any other failure keeps the current user and raises
  `sessionCheckFailed`, which `ProtectedRoute` renders as a retry alert instead of a
  redirect. Pages render inside `AppShell`.
- Pages load through `React.lazy` in `App.tsx`, so each ships in its own chunk, and
  `AppShell` wraps its `Outlet` in `Suspense` so the app bar stays while a page loads.
  `RouteErrorBoundary`, a pathless layout route in `App.tsx`, puts every page inside an
  error boundary that clears when the path changes, so a failing page, or a page
  whose chunk fails to load, keeps the app bar. `vite.config.ts` groups third-party
  code into the `react`, `mui`, and `forms` vendor chunks; add a large new dependency
  to one of them in `VENDOR_CHUNKS`.
- Admin pages sit behind `AdminRoute`, inside `ProtectedRoute`, which sends non-admins
  to `/`. `pages/AdminPage.tsx` builds its tabs and its descendant routes from one
  `SECTIONS` array, so a new admin screen is one more entry there.
- Server state goes through TanStack Query. `main.tsx` provides one `QueryClient`.
  Each resource gets an API module built with `resource()` from `api/resources.ts` and
  a hooks module, such as `hooks/users.ts`, with a `useQuery` for its list and
  `useResourceMutations()` from `hooks/resources.ts`, which invalidates the resource's
  key, and any `alsoInvalidate` keys, after a change and hands each record an update
  saves to `onUpdated`, which the users hooks use to keep the auth store current. A
  record's detail query is keyed `[...listKey, id]`; a delete removes it with
  `removeQueries` before invalidating the list, because the list's prefix invalidation
  would otherwise refetch the deleted record and show it from cache through the
  retries. `useSessionQueryCache()` in `App.tsx` clears the cache whenever the
  signed-in account changes, so one account never sees another's data.
- Forms use React Hook Form with Zod schemas; a form in a dialog is a `FormDialog` whose
  fields are `FormTextField`, `FormSelectField`, and `FormSwitchField` from
  `components/common/`. Request errors surface through `useApiError`, which
  `FormDialog` shows above the fields. The 422 envelope carries no field details
  (`app.py` only logs them), so the Zod schemas enforce every backend validation rule;
  otherwise the user sees just "Invalid request".
- A list of records with create, edit, and delete dialogs is a `RecordSection`, given
  the resource's mutations and a `renderDialog` for its form dialog; without
  `mutations.remove`, no row offers Delete. The section closes whichever dialog is open
  when a save or delete settles, so `FormDialog` and `ConfirmDialog` cannot be
  dismissed while their request runs, and a dialog built another way must hold itself
  open the same way. `QueryState` renders a query's spinner, error, or data.
- A record's detail view shows its history with `RecordAuditLogTab`, given the table
  and the record's id; a form beside it passes `alsoInvalidate: [['audit-logs']]` to
  its mutations so the history refreshes after a save. The admin screen's Audit tab is
  `AdminAuditLogTab`. Both render `AuditLogTab`, which pages with `useInfiniteList`
  and `InfiniteScrollSentinel`.
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
- Component files export only components: `react-refresh/only-export-components` warns
  on any other export except a primitive constant, and CI fails on warnings, so shared
  constants and helpers live in `.ts` modules.
- Every file starts with a `@file` JSDoc block, and every function, interface, and
  type alias has JSDoc without types in its tags. Functions stay under 50 lines.
- Prettier: single quotes, no semicolons, 4-space indentation, print width 90.
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

## Shell Scripts

- Every new or changed shell script gets a test, `scripts/tests/test-<script>.sh`, in
  the style of the existing ones. The test runs the script against a disposable
  directory, copying the script there and rewriting absolute system paths such as
  `/var/log` with `sed` when it writes to them. It puts stub commands (`docker`,
  `systemctl`, `lsof`, `rclone`, `curl`, and so on) first on `PATH`, checks that each
  shadows the real command, and has each log its call to a `commands` file. It asserts
  on that log, and on the files the script wrote, with grep-based `assert_contains` and
  `refute_contains`, because a bare `! grep` never fails under `set -e`, or with `diff`
  when the exact sequence of calls matters, as `test-entrypoint.sh` does.
- Tests run under macOS's Bash 3.2 as well as on Linux, so they avoid `mapfile`,
  associative arrays, `${var,,}`, `sed -i`, `grep -P`, and GNU-only options such as
  `tail -z` and `find -printf`. A test that cannot run on the machine, because its
  script needs Linux, as `backup.sh` does, or a tool is missing, says why and exits
  with status 77. `scripts/tests/run-all.sh` counts that as a skip locally and as a
  failure in CI, where every test must run.
- A test that needs a real server or image, as `test-nginx-site.sh` and
  `test-backend-image.sh` do, runs containers instead of stubs. It names every
  container, image, and volume it creates after itself and its process id, removes
  them however it exits, and exits 77 without a running Docker daemon or a tool it
  needs.
- Every script names its shell in a shebang (`#!/bin/sh`, `#!/bin/bash`, or
  `#!/usr/bin/env bash`). `run-all.sh` checks each one with `sh -n` or `bash -n` to
  match, and fails a `.sh` file without one. Tests are mode 644 and run as
  `bash <file>`. `npm run test:scripts` runs the whole suite locally, and CI runs the
  same file on Ubuntu, where `sh` is dash, as it is in the backend image.

## Git

- `plans/` holds implementation plans; move finished plans to `plans/archive/`.
- `staging` is the default branch. Feature branches fork from `origin/staging`, PRs
  target it, and review diffs use `origin/staging...HEAD`.
- A release is a PR from `staging` into `main`, merged with "Create a merge commit".
  Never squash or rebase it: both rewrite staging's commits, so `main` would stop
  containing them and every later release would conflict. After the merge,
  `git diff origin/staging origin/main` must print nothing.
- A hotfix branches from `origin/main` and targets `main`. Bring it back into `staging`
  through a throwaway branch cut from `origin/main` (`ai/staging.md`, "Branches and
  releases"), never with `main` as a PR's head, since merged head branches are deleted.
- Issues close when their PR merges into `staging`, before they reach production:
  GitHub honors closing keywords only on the default branch.
- Commits and pushes are the user's; never run them unasked.
