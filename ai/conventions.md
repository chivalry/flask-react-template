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
  or `paginate_and_dump` builds the response.
- Services in `src_back/services/` own business logic. Reuse `CRUDService` for
  top-level resources and `ChildRecordService` for nested ones. Its
  `get_for_parent()` is how nested routes validate parent ownership before mutating;
  `require_parent()` in `utils.py` answers 404 when the parent is missing, and
  `create()` and `update()` keep the URL's parent id authoritative over any parent id
  in the body.
- Schemas extend `BaseSchema` (marshmallow-sqlalchemy auto schema with
  `load_instance = False`), set `Meta.model`, and mark `BaseSchema.AUDIT` dump-only.
  Auto schemas omit foreign-key columns; a child schema that accepts the parent id
  in the body sets `include_fk = True`.
- Auth is a Flask-Login session cookie. Protect routes with `@login_required` or
  `@admin_required` (401 for anonymous callers, 403 for non-admins).
- Every function and class has a Google-style docstring, and `pydoclint` checks that
  arguments and returns match it. Functions stay under 50 physical lines
  (`scripts/check_function_length.py`). `basedpyright` runs in standard mode.
- Python uses single quotes (Ruff format) and a line length of 90.

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
- Forms use React Hook Form with Zod schemas; request errors surface through
  `useApiError`.
- Every file starts with a `@file` JSDoc block, and every function, interface, and
  type alias has JSDoc without types in its tags. Functions stay under 50 lines.
- Prettier: single quotes, no semicolons, 4-space indentation, print width 90.

## Git

- `plans/` holds implementation plans; move finished plans to `plans/archive/`.
- Review diffs use `origin/main...HEAD` unless the project adopts a staging branch, in
  which case record the base here.
- Commits and pushes are the user's; never run them unasked.
