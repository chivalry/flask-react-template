# Issue #10: Fix four defects found in projects generated from the template

## Context

Projects generated from this template inherit four defects that `chivalry/hukilau`
fixed in its own copy:

1. The `app` fixture never disposes its engine, so a long run against PostgreSQL (CI
   runs one through `TEST_DATABASE_URL`) exhausts the server's connections.
2. `ProtectedRoute` forgets the requested URL, and `useAuthFormState` always goes to
   `/` after sign-in.
3. `scripts/deploy.sh` leaves the containers of removed services running.
4. Nothing removes a stored upload.

Fixes 1 to 3 port hukilau commits `3db8211`, `404b8c6`, and `7e5889d`. Fix 4 is new code
modelled on ponies (`delete_upload`) and treasured-souvenirs (commit first, then remove
the file). No backend endpoint or API client function changes.

Decisions made while planning (2026-10-24):

- **Removing files after the commit gets a hook.** The issue says `delete_upload` is "for
  `before_delete` implementations to call" and also that services remove files "after the
  commit". `before_delete` runs before `db.session.commit()`, so both cannot hold. The
  chosen fix adds a no-op `after_delete(record)` to `CRUDService` and
  `ChildRecordService`, called after the commit. In SQLAlchemy 2.0.49, a deleted
  object's loaded columns stay readable after the commit. A flush drops the object from
  the identity map (`orm/session.py:3425`), and the commit expires only identity-map
  objects before it detaches the deleted ones (`session.py:1134-1141`).
- **The venv is rebuilt with uv-managed Python 3.12.** `.venv/bin/python` points at
  Homebrew's `python@3.14`, which Homebrew no longer has (it has 3.13 and 3.15). Until
  the venv is rebuilt, `pytest` and `lint:py` cannot run. `python3` is now 3.15, and
  psycopg2-binary 2.9.10 publishes no wheel for it. Version 3.12 matches CI
  (`ci.yml:33`) and Docker.

Corrections to the issue text:

- Only `52160cf` changed `conftest.py` after hukilau was generated from `99bad26`;
  `8aeaa18` did not touch the file. Applying the hunk by hand is still right, since
  `52160cf` rewrote its context lines.
- hukilau's tests never use a non-empty hash, and its `ProtectedRoute` test checks only
  the pathname. The tests below cover both, which the acceptance criterion requires.

## Branch

`issue-10-fix-four-defects-found-in-projects` — already checked out; PR #33 exists. The
branch was cut from `origin/main` at `fd962d2`, the merge of PR #9 (code splitting),
which landed during planning. Every line number below was checked against that commit.

## Prerequisite: rebuild the venv

```bash
rm -rf .venv
uv venv --seed --python 3.12 .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python --version   # Python 3.12.x
```

## Change

**12 files to edit**: `src_back/tests/conftest.py`, `src_back/services/base.py`,
`src_back/tests/test_base_service.py`, `src_back/utils.py`,
`src_back/tests/test_utils.py`, `src_front/src/components/ProtectedRoute.tsx`,
`src_front/src/test/ProtectedRoute.test.tsx`, `src_front/src/hooks/useAuthFormState.ts`,
`src_front/src/test/Login.test.tsx`, `scripts/deploy.sh`, `ai/conventions.md`,
`README.md`.

Line numbers refer to each file before any edit; once an insertion shifts them, match by
content.

### src_back/tests/conftest.py — dispose the engine (hukilau `3db8211`)

After line 60 (`_db.drop_all()`), still inside `with app.app_context():`, add:

```python
        # Close this app's pooled connections now. Waiting for garbage collection lets a
        # long run exhaust Postgres's connection limit.
        _db.engine.dispose()
```

### src_back/services/base.py — `after_delete` hook on both services

CRUDService class docstring, lines 17 to 21, becomes:

```python
    """Generic service for top-level resources with full CRUD operations.

    Subclasses may override :meth:`before_delete` for side effects that must run
    before the row is deleted, and :meth:`after_delete` for ones that must wait
    for the commit, such as removing the record's stored files.
    """
```

In `CRUDService.delete`, line 97 becomes two lines:

```python
        Calls :meth:`before_delete` before the row is removed and
        :meth:`after_delete` once the deletion is committed.
```

After line 110 (`db.session.commit()`), add `self.after_delete(record)` before
`return True`. After line 118, the end of `CRUDService.before_delete`, add:

```python

    def after_delete(self, record: T) -> None:
        """Run side effects once a deletion is committed. Override in subclasses.

        This is where a service removes the record's stored files, through
        :func:`~src_back.utils.delete_upload`: a commit that fails never reaches
        this hook, so the row and its files stay together.

        Args:
            record: The deleted record, now detached from the session; the
                column values it had are still readable.
        """
```

In the ChildRecordService class docstring, line 127 (`be reached through the parent that
owns it.`) becomes:

```python
    be reached through the parent that owns it. :meth:`before_delete` and
    :meth:`after_delete` work as they do on :class:`CRUDService`.
```

In `ChildRecordService.delete`, lines 231 and 232 become:

```python
        Calls :meth:`before_delete` before the row is removed and
        :meth:`after_delete` once the deletion is committed. Existence was
        already established by :meth:`get_for_parent`, so nothing is returned.
```

After line 239 (`db.session.commit()`), add `self.after_delete(record)`. After line 246,
the end of `ChildRecordService.before_delete`, add the same `after_delete` method as
above.

### src_back/tests/test_base_service.py — record and pin the new hook

- After line 1, add `from sqlalchemy import inspect`.
- `RecordingCRUDService` (lines 21 to 27): add
  `self.committed: list[tuple[str, bool]] = []` to `__init__` and the method below.
  `RecordingChildService` (lines 30 to 36) gets the same, typed
  `list[tuple[str | None, bool]]` and recording `record.body`.

    ```python
        def after_delete(self, record: Widget) -> None:
            # A deleted record is detached only once its deletion is committed.
            self.committed.append((record.name, inspect(record).detached))
    ```

- Line 88: rename to `test_crud_delete_calls_hooks_and_removes_record` and add
  `assert service.committed == [('alpha', True)]` after line 92.
- After line 99, inside `test_crud_delete_returns_false_for_missing_record`, add
  `assert service.committed == []`.
- Line 168: rename to `test_child_delete_calls_hooks_and_removes_record` and add
  `assert service.committed == [('doomed', True)]` after line 172.
- Add the no-op tests that keep coverage at 100%: one after line 104 and one after
  line 179.

    ```python
    def test_crud_default_after_delete_is_a_no_op(db: SQLAlchemy) -> None:
        widget = _make_widget(db)
        assert CRUDService(Widget, Widget.name).after_delete(widget) is None


    def test_child_default_after_delete_is_a_no_op(db: SQLAlchemy) -> None:
        note = _make_note(db, _make_widget(db))
        service = ChildRecordService(WidgetNote, 'widget_id', WidgetNote.id)
        assert service.after_delete(note) is None
    ```

### src_back/utils.py — `delete_upload`

Line 16 becomes `from flask import Response, current_app, jsonify, request`, and after
line 19 add `from werkzeug.security import safe_join`. After line 272, the end of
`validate_image_file`, add:

```python
def delete_upload(filename: str | None) -> None:
    """Remove a stored upload from ``UPLOAD_FOLDER``, ignoring one already gone.

    Call it after the commit that stops referencing the file, as a service's
    ``after_delete`` does, so a failed commit never leaves a row pointing at a
    removed file. An empty name does nothing, and a name that would resolve
    outside ``UPLOAD_FOLDER`` is ignored, just as ``send_from_directory``
    refuses to serve one.

    Args:
        filename: Path of the file relative to ``UPLOAD_FOLDER``, as the record
            stores it, or ``None`` for a record without a file.
    """
    if not filename:
        return
    path = safe_join(current_app.config['UPLOAD_FOLDER'], filename)
    if path is not None:
        Path(path).unlink(missing_ok=True)
```

The empty-name guard is required. Werkzeug's `safe_join` skips an empty component
(`security.py:177`), so `''` would resolve to the folder itself and `unlink` would
raise.

### src_back/tests/test_utils.py — `delete_upload` tests

Add `from pathlib import Path` after line 3, and add `delete_upload,` between `conflict,`
(line 19) and `dump_or_404,` (line 20). Between line 259 and the
`# -- admin_required` header on line 262, add a section whose header is padded with
dashes to the same width as the others. The `app` fixture runs each test inside an app
context, so `current_app` resolves.

```python
# -- delete_upload ------------------------------------------------------------


def _upload_folder(app: Flask) -> Path:
    folder = Path(app.config['UPLOAD_FOLDER'])
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def test_delete_upload_removes_the_stored_file(app: Flask) -> None:
    stored = _upload_folder(app) / 'photo.png'
    stored.write_bytes(PNG_BYTES)
    delete_upload('photo.png')
    assert not stored.exists()


def test_delete_upload_ignores_a_missing_file(app: Flask) -> None:
    _upload_folder(app)
    assert delete_upload('missing.png') is None


@pytest.mark.parametrize('filename', [None, ''])
def test_delete_upload_does_nothing_without_a_filename(
    app: Flask, filename: str | None
) -> None:
    folder = _upload_folder(app)
    assert delete_upload(filename) is None
    assert folder.is_dir()


def test_delete_upload_leaves_files_outside_the_upload_folder(app: Flask) -> None:
    outside = _upload_folder(app).parent / 'outside.txt'
    outside.write_text('keep')
    delete_upload('../outside.txt')
    delete_upload(str(outside))
    assert outside.exists()
```

### src_front/src/components/ProtectedRoute.tsx — remember the location

Ported verbatim from hukilau `404b8c6`.

- Line 4: `import { Navigate, Outlet, useLocation } from 'react-router-dom'`.
- Docstring lines 42 to 47 become:

    ```tsx
     * retry alert replaces the redirect. The redirect replaces the history entry,
     * so the back button does not loop between the guarded route and login, and
     * remembers the requested page in its state, so signing in returns there.
     *
     * @returns Nothing while loading, the matched child route for a signed-in
     *   user, the retry alert after a failed session check, or a redirect to
     *   `/login` that remembers the requested page.
    ```

- Insert `const location = useLocation()` as the first line of the function body
  (before line 50). The hook has to run before the early returns.
- Line 57: `return <Navigate to="/login" replace state={{ from: location }} />`.

### src_front/src/hooks/useAuthFormState.ts — return there after sign-in

Ported verbatim from hukilau `404b8c6`. Line 4 becomes
`import { useLocation, useNavigate } from 'react-router-dom'`. After the imports
(line 8), insert:

```ts
/** What `ProtectedRoute` records about the page a signed-out visitor asked for. */
interface RedirectState {
    from?: { pathname?: string; search?: string; hash?: string }
}

/**
 * Find where to go after signing in.
 *
 * @param state - The login page's location state.
 * @returns The requested path with its query and hash, or `/` without one.
 */
function requestedPath(state: unknown): string {
    const from = (state as RedirectState | null)?.from
    if (!from?.pathname) return '/'
    return `${from.pathname}${from.search ?? ''}${from.hash ?? ''}`
}
```

The `@returns` text of the hook's docstring, lines 13 to 16, becomes:

```ts
 * @returns The current API error message, or null, and `handleAuthAction`,
 *   which runs an auth request, stores the user it returns, and navigates to
 *   the requested page, or to `/` when none was recorded. On failure it
 *   records the error message in `apiError` instead of throwing.
```

After line 19 (`const navigate = useNavigate()`), add `const location = useLocation()`.
Line 43 becomes `navigate(requestedPath(location.state))`. `Register.tsx` shares the
hook and needs no edit.

### src_front/src/test/ProtectedRoute.test.tsx — redirect records path, query, hash

Line 3 adds `useLocation` to the `react-router-dom` import. Replace lines 19 to 29 with:

```tsx
// Shows the login page and the location the guard recorded in the redirect's state.
const LoginStub = () => {
    const from = useLocation().state?.from
    return (
        <>
            <div>Login page</div>
            <div>{`Recorded ${from?.pathname}${from?.search}${from?.hash}`}</div>
        </>
    )
}

const renderProtectedRoute = (path = '/protected') =>
    render(
        <MemoryRouter initialEntries={[path]}>
            <Routes>
                <Route path="/login" element={<LoginStub />} />
                <Route element={<ProtectedRoute />}>
                    <Route path="/protected" element={<div>Protected content</div>} />
                </Route>
            </Routes>
        </MemoryRouter>,
    )
```

After the `redirects to /login when the auth store has no user` test, which ends at
line 59, add:

```tsx
    it('records the requested path, query, and hash in the redirect', () => {
        renderProtectedRoute('/protected?tab=2#top')

        expect(screen.getByText('Recorded /protected?tab=2#top')).toBeInTheDocument()
    })
```

### src_front/src/test/Login.test.tsx — sign-in returns to the recorded page

Line 4 adds `useLocation` to the `react-router-dom` import. Replace lines 23 to 31 with:

```tsx
// Shows the full location it landed on, so a test can check the query and hash too.
const RequestedPage = () => {
    const { pathname, search, hash } = useLocation()
    return <div>{`Requested page ${pathname}${search}${hash}`}</div>
}

const renderLogin = (state?: unknown) =>
    render(
        <MemoryRouter initialEntries={[{ pathname: '/login', state }]}>
            <Routes>
                <Route path="/login" element={<Login />} />
                <Route path="/" element={<div>Home page</div>} />
                <Route path="/widgets/:widgetId" element={<RequestedPage />} />
            </Routes>
        </MemoryRouter>,
    )
```

After `signInWith`, which ends at line 41, add:

```tsx
const renderLoginAndSignIn = async (state: unknown) => {
    const user = userEvent.setup()
    vi.mocked(login).mockResolvedValue({ data: testUser } as AxiosResponse<AuthUser>)
    renderLogin(state)
    await signInWith(user, 'user@example.com', 'password123')
}
```

After the `signs in, stores the user, and navigates to / on success` test, which ends at
line 80 and still covers a direct sign-in with no state, add three tests. Together they
cover every branch of `requestedPath` for the 100% branch threshold.

```tsx
    it('returns to the page the guard recorded, with its query and hash', async () => {
        await renderLoginAndSignIn({
            from: { pathname: '/widgets/12', search: '?tab=notes', hash: '#latest' },
        })

        expect(
            await screen.findByText('Requested page /widgets/12?tab=notes#latest'),
        ).toBeInTheDocument()
    })

    it('returns to a recorded page that has no query or hash', async () => {
        await renderLoginAndSignIn({ from: { pathname: '/widgets/12' } })

        expect(await screen.findByText('Requested page /widgets/12')).toBeInTheDocument()
    })

    it('goes to / when the recorded page has no path', async () => {
        await renderLoginAndSignIn({ from: { search: '?tab=notes' } })

        expect(await screen.findByText('Home page')).toBeInTheDocument()
    })
```

### scripts/deploy.sh — remove orphaned containers (hukilau `7e5889d`)

Line 131 (`compose up -d --build`) becomes:

```bash
# A service dropped from the Compose files would otherwise leave its container running.
compose up -d --build --remove-orphans
```

Line 116 (`compose up -d db`, for the pre-migration backup) and line 128
(`compose down`) stay as they are.

### ai/conventions.md — the file-removal rule

After line 26, the end of the services bullet, add:

```markdown
- A service removes a stored file only after the commit that stops referencing it,
  through `delete_upload()` in `utils.py`, which ignores a file that is already gone:
  in `after_delete` for a deleted record, and after its own commit when an update
  replaces the file. A failed commit then leaves the row and its file in place.
```

### README.md — Uploads section

After line 159 (`volume persists files across rebuilds.`), add a blank line and:

```markdown
To remove a stored file, a service overrides `after_delete` and calls `delete_upload()`,
also in `src_back/utils.py`, so the file goes only once the row's deletion is committed.
A file that is already gone is ignored.
```

## Parallelism

**First, alone:** the venv prerequisite, then the PostgreSQL baseline (Verification
step 1). Both run before any edit.

**Can be done in parallel**, since no two groups share a file:

- A: `conftest.py`
- B: `services/base.py` with `test_base_service.py`
- C: `utils.py` with `test_utils.py`
- D: `ProtectedRoute.tsx` with `ProtectedRoute.test.tsx`
- E: `useAuthFormState.ts` with `Login.test.tsx`
- F: `scripts/deploy.sh`
- G: `ai/conventions.md` with `README.md`

**Must be sequential:** run the targeted tests once the batch is done (backend B and C in
one pytest call; frontend D and E in one Vitest call). Then run the full parallel batch,
then the PostgreSQL run after the fix (Verification steps 2 to 5).

## No other changes needed

- `scripts/deploy.sh:128`: `compose down` only warns about an orphan, and the `up` that
  follows removes it. `scripts/backup.sh` starts no Compose containers (`compose exec`
  at line 81, a plain `docker run --rm` at line 114), so `--remove-orphans` cannot touch
  a backup. `scripts/up.sh:66` and `package.json:30` (`docker:prod:up`) are not the
  server deploy.
- `Register.tsx:72` uses the shared hook. Its test still lands on `/` because
  `/register` carries no state. The Login page's Register link (`Login.tsx:54`) does not
  forward the state, so a visitor who registers instead of signing in lands on `/`.
  #10's criteria cover sign-in only.
- `AppShell.tsx:61`: logout navigates to `/login` without state, so the next sign-in
  lands on `/`, as it should.
- `App.tsx:43`: the catch-all redirect sits outside `ProtectedRoute`, so in the bare
  template the only protected URL is `/` with any query and hash. Derived projects nest
  their pages under `ProtectedRoute`. The lazy-loaded pages and `Suspense` boundary from
  PR #9 do not affect the redirect state.
- `.github/workflows/ci.yml:58-63` already runs pytest against PostgreSQL. Shell-script
  checks belong to #15.
- No migration, model, schema, or API contract change. Upload serving
  (`app.py:287`) is unchanged.
- Follow-up outside this PR: #26 says "A parent's delete removes its files first". Under
  the rule this PR sets, the parent service's `after_delete` removes them after the
  commit, and `PhotoService` can renumber siblings in `before_delete` and remove the
  file in `after_delete`.

## Verification

1. Baseline before any edit, after the venv prerequisite. Docker was running and port
   55432 was free on 2026-10-24.

    ```bash
    docker run --rm -d --name frt-issue-10-pg -p 55432:5432 \
      -e POSTGRES_USER=app -e POSTGRES_PASSWORD=app -e POSTGRES_DB=app \
      postgres:16 -c max_connections=20
    until docker exec frt-issue-10-pg pg_isready -h 127.0.0.1 -U app >/dev/null 2>&1
    do sleep 1; done
    TEST_DATABASE_URL=postgresql://app:app@localhost:55432/app \
      .venv/bin/python -m pytest --no-cov
    ```

    Expected, though not guaranteed because garbage-collection timing varies: errors
    with `sorry, too many clients already`. Record the result and leave the container
    running for step 5.

2. Targeted tests after the edits:

    ```bash
    .venv/bin/python -m pytest src_back/tests/test_base_service.py \
      src_back/tests/test_utils.py --no-cov
    npx vitest run ProtectedRoute.test.tsx Login.test.tsx Register.test.tsx
    ```

3. Deploy script: run `bash -n scripts/deploy.sh`, then
   `grep -n 'compose up' scripts/deploy.sh`, which prints `116:  compose up -d db` and
   `132:compose up -d --build --remove-orphans`.

4. Full batch, launched together: `npm run test`, `npm run lint -- --max-warnings=0`,
   `npm run lint:py`, `npm run lint:md`, `npx prettier --check .`, `npm run build`, and
   `npm run fallow -- --base origin/main`, the last two as CI runs them. Both suites
   must report 100% coverage.

5. PostgreSQL after the fix, in the same 20-connection container. It must pass with 100%
   coverage and no connection errors:

    ```bash
    TEST_DATABASE_URL=postgresql://app:app@localhost:55432/app .venv/bin/python -m pytest
    docker stop frt-issue-10-pg
    ```

6. Optional manual check: run `npm run docker:up`, then `npm run docker:url`. Register an
   account, sign out, open `<url>/?tab=2#top`, and sign in: the address bar shows
   `/?tab=2#top`. Opening `<url>/login` directly and signing in lands on `/`. Finish
   with `npm run docker:down`.
