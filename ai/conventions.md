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
- A service removes a stored file only after the commit that stops referencing it,
  through `delete_upload()` in `utils.py`, which ignores a file that is already gone:
  in `after_delete` for a deleted record, and after its own commit when an update
  replaces the file. A failed commit then leaves the row and its file in place.
- Schemas extend `BaseSchema` (marshmallow-sqlalchemy auto schema with
  `load_instance = False`), set `Meta.model`, and mark `BaseSchema.AUDIT` dump-only.
  Auto schemas omit foreign-key columns; a child schema that accepts the parent id
  in the body sets `include_fk = True`. A schema that accepts a list of ids checks it
  in a `@validates` method with `validate_ids_exist(model, ids, label)`, one `COUNT`
  query, so an unknown id fails with a 422.
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
  `422`, or `500`. Validation failures are `422`.
- Paginated lists are `{"items": [...], "total", "page", "pages", "per_page"}`, with
  `per_page` capped at 100.
- Image uploads go through `validate_image_file()`; stored files are served from
  `/uploads/<filename>` to signed-in users only; bodies over 25 MB return `413`.

## Frontend

- The axios client (`api/client.ts`) uses `baseURL: '/api'` and `withCredentials`.
  Its interceptors copy the server's `error` text onto `error.message` and notify the
  auth store on a 401.
- The Zustand auth store holds the signed-in user. `fetchMe()` runs once on mount and
  `ProtectedRoute` waits for it; login and register store the user from their own
  response, and a `/me` response that lands after a sign-in or sign-out is discarded
  as stale. Only a 401 from `/me` ends the session; any other failure keeps the
  current user and raises `sessionCheckFailed`, which `ProtectedRoute` renders as a
  retry alert instead of a redirect. Pages render inside `AppShell`.
- Pages load through `React.lazy` in `App.tsx`, so each ships in its own chunk, and
  `AppShell` wraps its `Outlet` in `Suspense` so the app bar stays while a page loads.
  `vite.config.ts` groups third-party code into the `react`, `mui`, and `forms` vendor
  chunks; add a large new dependency to one of them in `VENDOR_CHUNKS`.
- Forms use React Hook Form with Zod schemas; request errors surface through
  `useApiError`. The 422 envelope carries no field details (`app.py` only logs them),
  so the Zod schemas enforce every backend validation rule; otherwise the user sees
  just "Invalid request".
- Component files export only components: `react-refresh/only-export-components` warns
  on any other export except a primitive constant, and CI fails on warnings, so shared
  constants and helpers live in `.ts` modules.
- Every file starts with a `@file` JSDoc block, and every function, interface, and
  type alias has JSDoc without types in its tags. Functions stay under 50 lines.
- Prettier: single quotes, no semicolons, 4-space indentation, print width 90.

## Git

- `plans/` holds implementation plans; move finished plans to `plans/archive/`.
- Review diffs use `origin/main...HEAD` unless the project adopts a staging branch, in
  which case record the base here.
- Commits and pushes are the user's; never run them unasked.
