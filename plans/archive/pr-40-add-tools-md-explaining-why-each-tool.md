# Issue #12: Add tools.md Explaining Why Each Tool and Library Is in the Repository

## Context

Nothing in the repository says why each tool and library is there. `ai/project.md`
covers layout and commands, `README.md:10-16` names the stack, and the pins in
`requirements.txt`, `requirements-dev.txt`, and `package.json` carry no reasons. This
adds a root `tools.md` modeled on hukilau's (`7ac8d12`, 2026-10-22, 300 lines, unchanged
since): one short entry per tool, in the nine groups the issue lists, which are
hukilau's sections without "The Mac". `README.md` and `ai/project.md` link to it.

The inventory, checked against this repository's code:

- **Python**: the 12 runtime pins (`requirements.txt:3-15`) and the five dev pins that
  remain after the removal below each get an entry. Werkzeug and Alembic get entries
  too, as in hukilau: the code imports them (`src_back/models.py:14`,
  `src_back/app.py:20`, `src_back/utils.py:19-20`, `migrations/env.py:4`), but they
  arrive with Flask and Flask-Migrate rather than from pins of their own.
- **npm**: the one `package.json` has 12 `dependencies` (`:50-63`) and 26
  `devDependencies` (`:64-91`), and every one is used.
- **Server**: `scripts/provision.sh:34-35` installs `ca-certificates`, `curl`, `git`,
  `vim`, `dnsutils`, `certbot`, and `python3-certbot-nginx`, which brings nginx
  (`:60`); `:54-55` installs Docker's engine, CLI, containerd, and the Buildx and
  Compose plugins. `scripts/install-backup.sh:27-30` installs rclone, and
  `scripts/systemd/` holds five units and the certbot `OnFailure` drop-in.
- **Decided with the user: `pytest-flask` is removed, not documented.** No test uses
  it. With the plugin unloaded, `pytest -p no:flask` drops `flask-1.3.0` from the
  `plugins:` line and all 120 backend tests still pass. `conftest.py:55` pushes its own
  app context and `:66-68` defines its own `client`.
- **Inferred, stated nowhere in the repository**: the reasons given for Vim (the editor
  for the server's `.env`) and ca-certificates (HTTPS for Docker's apt repository).
  Correct those two entries if the intent was different.

Where hukilau's text describes hukilau, the entries are adapted rather than copied:

- **Dropped, absent here**: watchdog, TanStack Query, `docker-compose.override.yml`
  and `docker-compose.lan.yml`, GHCR and the arm64 image job, `release.sh`, the
  Raspberry Pi pieces (Raspberry Pi OS, Avahi, `nginx-lan.conf.template`), rsync,
  launchd, osascript, the script tests and CI's `bash -n` check, and jq in CI.
- **Changed**: React 19, not 18. gunicorn serves both Compose stacks
  (`docker-compose.yml:35`, `docker/entrypoint.sh:13-17`). The user loader has no
  deactivation check (`src_back/app.py:47-57`). Queries go through `db.session`, not
  `select` statements (`ai/project.md:63-64`). Flask-Migrate has no `check` step. The
  backup timer fires at 02:30 UTC (`scripts/systemd/backup.timer:6`). Deploys wait only
  for the backend's health. Nothing claims Bash 3.2 compatibility, and the Vitest setup
  pins no time zone.
- **Added**: `babel-plugin-react-compiler`, the `alpine` image, git, Vim,
  ca-certificates, `api.ipify.org`, the Vitest explorer, and `.vscode/launch.json`.

## Branch

`issue-12-add-tools-md-explaining-why-each-tool` — already checked out; PR #40 exists.
An earlier run pushed this branch for PR #39, which is now closed. The branch is
`origin/main` (`2b19d5c`) plus the empty start commit `1f8d6c9`, so it was reused
rather than pushed again.

## Change

**4 files, 3 edits and 1 new file**: `tools.md` (new), `requirements-dev.txt`,
`README.md`, and `ai/project.md`.

### `tools.md` — new

Write exactly this, ending with a newline (`.editorconfig:10`). As written it passes
`markdownlint-cli2` with `.markdownlint.json` and `prettier --check` with `.prettierrc`,
and no line exceeds 90 characters, so neither tool should change it.

```markdown
# Tools and Libraries

Why each tool and library in this repository is here, one short entry apiece. The
pinned versions live in `requirements.txt`, `requirements-dev.txt`, and `package.json`;
the server-side tools are installed by the scripts under `scripts/` and the images under
`docker/`. `ai/project.md` describes the repository's own scripts and commands, and the
runbooks `ai/backups.md` and `ai/tls.md` describe how the operations tools are used.
This file only explains what each one is for.

## Languages and runtimes

- **Python 3.12**: the backend language, and the oldest version the code runs on: it
  uses PEP 695 generics, which arrived in 3.12. The backend image is
  `python:3.12-slim`, CI and the dev container install 3.12, and `pyproject.toml` makes
  it Ruff's target and basedpyright's Python version. Local work runs through
  `.venv/bin/`, a virtual environment filled by pip from `requirements-dev.txt`, never
  through the system interpreter.
- **Node.js 22 and npm**: run the frontend toolchain: Vite, Vitest, ESLint, Prettier,
  and the rest of `package.json`. The frontend images build on `node:22-slim`, CI and
  the dev container pin 22, and `npm ci` installs exactly what `package-lock.json`
  records.
- **TypeScript**: the frontend language, compiled by Vite and checked by `tsc -b` over
  three project references: the app, `vite.config.ts`, and the tests.
- **Bash and POSIX sh**: the scripts. `docker/entrypoint.sh` and the local helpers
  `up.sh`, `down.sh`, `docker-url.sh`, and `worktree-setup.sh` are POSIX sh; the server
  and deployment scripts and the Claude Code hook are Bash.
- **PostgreSQL 16**: the database in development and production, from the
  `postgres:16` image. CI runs the backend tests against it as well.
- **SQLite**: the in-memory database the backend tests use by default, so the suite
  needs no server; `TEST_DATABASE_URL` switches it to PostgreSQL.

## Backend runtime libraries

Installed from `requirements.txt` into the backend image and into `.venv`.

- **Flask**: the web framework. `src_back/app.py` builds the app through a factory,
  registers one blueprint per domain, maps exceptions to JSON error envelopes, and
  serves the built SPA and the login-protected uploads. Its `flask` command applies
  the migrations and runs the local development server.
- **Werkzeug**: Flask's underlying WSGI toolkit, installed with Flask rather than
  pinned on its own. The code uses it directly for password hashing in
  `src_back/models.py`, for the `NotFound` exception the SPA fallback catches when no
  build is present, and for the `FileStorage` type and `safe_join` in the upload
  helpers.
- **SQLAlchemy 2**: the ORM. Models declare `Mapped[]` columns on the shared `Base` in
  `src_back/extensions.py`. It is pinned to the 2.0 line because 2.1 switches
  `postgresql://` URLs to the psycopg 3 driver.
- **Flask-SQLAlchemy**: binds SQLAlchemy to the Flask app and provides the `db.session`
  every query goes through.
- **psycopg2-binary**: the PostgreSQL driver. No module imports it; SQLAlchemy loads it
  for every `postgresql://` URL. The prebuilt wheel means the slim image needs no
  compiler.
- **Flask-Migrate**: wraps Alembic in the `flask db` commands that author and apply the
  migrations in `migrations/`. The container entrypoint runs `db upgrade` on every
  start.
- **Alembic**: the migration engine behind Flask-Migrate, which installs it.
  `migrations/alembic.ini` sets the `YYYY_MM_DD_<rev>_<slug>` file names, and
  `migrations/env.py` takes the model metadata from the Flask app.
- **Flask-Login**: session-cookie authentication. It provides `login_required`,
  `current_user`, the `UserMixin` on `User`, and the user loader; the app's
  unauthorized handler makes it answer a JSON 401 instead of redirecting. Login and
  registration make the session permanent, so a sign-in lasts 30 days past its latest
  request.
- **Flask-Cors**: adds CORS headers for the origins in `CORS_ALLOWED_ORIGINS`, with
  credentials allowed, so a frontend served from another origin can call the API with
  its session cookie.
- **marshmallow**: validates request bodies (422 on failure) and serializes responses.
  Every schema under `src_back/schemas/` is a marshmallow schema.
- **marshmallow-sqlalchemy**: generates schema fields from the SQLAlchemy models.
  `BaseSchema` extends its `SQLAlchemyAutoSchema`, so each schema only adds what the
  model does not already say.
- **filetype**: sniffs the MIME type of an uploaded file from its first bytes, so
  `validate_image_file()` trusts the content rather than the extension.
- **python-dotenv**: loads `.env` when `src_back/app.py` is imported, so the `flask`
  command, the seed, and pytest read the same settings on the host. In the containers
  Compose supplies the variables instead, and `.dockerignore` keeps `.env` out of the
  image.
- **gunicorn**: the WSGI server in both Compose stacks. `docker/entrypoint.sh` starts it
  after the migrations and the seed, with `GUNICORN_WORKERS` workers: 2 by default, 4
  in the production override. Work without Docker uses Flask's development server.

## Backend quality and test tools

Installed from `requirements-dev.txt` into `.venv` only; the backend image never has
them. `npm run lint:py` and `npm run test:back` run them, as do lint-staged and CI.

- **Ruff**: lints and formats the Python code. `pyproject.toml` selects the
  pycodestyle, Pyflakes, isort, pyupgrade, and pydocstyle rules with Google-style
  docstrings; the annotation, boolean-trap, pathlib, and simplification rules; and two
  preview rules that require PEP 695 generics. The formatter uses single quotes and a
  90-character line.
- **pydoclint**: checks that each existing docstring's arguments and returns match the
  function signature. Ruff's docstring rules decide where a docstring must exist;
  pydoclint decides whether it agrees with the code.
- **basedpyright**: the type checker, in standard mode. Its `[tool.pyright]` settings
  are the ones Pylance reads in the editor, so the command line and the editor agree.
- **`scripts/check_function_length.py`**: a repository script that fails any Python
  function over 50 physical lines. Ruff has no such rule, and this keeps the backend
  to the same cap ESLint enforces on the frontend.
- **pytest**: the backend test runner, over `src_back/tests/`. The fixtures in
  `conftest.py` build the app on an in-memory database and sign in test clients.
- **pytest-cov**: measures coverage with coverage.py and fails the run under 100%, the
  gate `pyproject.toml` sets with `--cov-fail-under=100`.

## Frontend runtime libraries

The `dependencies` in `package.json`: what the browser bundle ships.

- **React 19 and react-dom**: the UI library and its DOM renderer. `main.tsx` mounts
  the app under `StrictMode` inside an error boundary and the theme and router
  providers, and `App.tsx` loads each page with `React.lazy`, so every page ships in
  its own chunk.
- **MUI (`@mui/material`)**: the component library: the app bar, the sign-in and
  registration forms, the alerts, and the theme in `theme.ts`.
- **`@mui/icons-material`**: MUI's icon set. The app bar's logout icon is its only use
  so far.
- **Emotion (`@emotion/react`, `@emotion/styled`)**: MUI's styling engine. MUI requires
  both as peer dependencies even though no source file imports them, which is why
  `.fallowrc.json` tells fallow to ignore them.
- **Axios**: the HTTP client. `api/client.ts` sets `baseURL: '/api'` and
  `withCredentials`, and its interceptors copy the server's error text onto the error
  and tell the auth store about a 401.
- **React Router (`react-router-dom`)**: client-side routing. `App.tsx` holds the
  route table, and `ProtectedRoute` sends a signed-out visitor to the login page.
- **React Hook Form (`react-hook-form`)**: form state and validation for the sign-in
  and registration forms.
- **`@hookform/resolvers`**: the bridge that lets React Hook Form validate with the
  Zod schemas.
- **Zod**: the sign-in and registration schemas, which also type the form values, so
  the frontend checks the backend's rules before a request is sent.
- **Zustand**: the one store, holding the signed-in user and the session check that
  `ProtectedRoute` waits on.

## Frontend build, test, and quality tools

The `devDependencies` in `package.json`.

- **Vite**: the dev server and bundler. `vite.config.ts` sets `src_front` as the root,
  proxies `/api` and `/uploads` to the backend so the browser sees one origin, groups
  third-party code into the `react`, `mui`, and `forms` vendor chunks, and builds to
  `dist/`, which Flask serves locally and the nginx image serves in production.
- **`@vitejs/plugin-react`**: Vite's React plugin: the JSX transform, Fast Refresh,
  which updates a saved component in place, and the Babel pass that runs React
  Compiler.
- **`babel-plugin-react-compiler`**: React Compiler, which memoizes components and
  hooks automatically. `vite.config.ts` applies it to production builds only, so
  development and the tests run the authored source for readable debugging and
  accurate coverage.
- **TypeScript (`typescript`)**: the compiler. `npm run typecheck` runs `tsc -b` over
  the three project references, `npm run build` runs it before Vite, the pre-push hook
  runs the build, and a Claude Code hook runs it after every TypeScript edit. The
  `~6.0.0` range keeps it below 6.1, which typescript-eslint does not support yet.
- **`@types/node`, `@types/react`, `@types/react-dom`**: type declarations for Node,
  which `vite.config.ts` uses, and for React and react-dom, which ship none of their
  own.
- **Vitest**: the frontend test runner, configured in the `test` block of
  `vite.config.ts` so it shares Vite's resolution and plugins.
- **`@vitest/coverage-v8`**: the coverage provider, with 100% thresholds over every
  source file so an untested module fails the run instead of going unnoticed.
- **jsdom**: the browser environment the tests render into.
- **Testing Library (`@testing-library/react`, `@testing-library/user-event`,
  `@testing-library/jest-dom`)**: renders components and queries them the way a user
  sees them, drives them with realistic keyboard and pointer events, and adds the DOM
  matchers such as `toBeInTheDocument`.
- **ESLint**: the linter, in flat-config form in `eslint.config.js`, over
  `src_front/src`. It also caps source functions at 50 lines, the limit
  `scripts/check_function_length.py` mirrors for Python. CI runs it with
  `--max-warnings=0`.
- **`@eslint/js`**: ESLint's own recommended rule set.
- **typescript-eslint**: the TypeScript parser and rules for ESLint, including the
  unused-variable rule with the `_` prefix exemption.
- **`eslint-plugin-react-hooks`**: enforces the rules of hooks and effect dependencies.
- **`eslint-plugin-react-refresh`**: warns when a module exports something besides
  components, which would break Fast Refresh.
- **`eslint-plugin-jsdoc`**: requires a `@file` block in every source file and a JSDoc
  description on every function, interface, and type alias, with parameter and return
  descriptions and no types in the tags, since TypeScript supplies them. Tests are
  exempt.
- **`globals`**: the browser global names ESLint accepts as defined.
- **Prettier**: formats TypeScript, JSON, YAML, and Markdown with the settings in
  `.prettierrc`; `.prettierignore` keeps plans, caches, build and coverage output, and
  the lock file out. CI runs `prettier --check .`.
- **markdownlint-cli2**: lints Markdown with the rules in `.markdownlint.json`:
  90-character lines and 4-space nested lists. `npm run lint:md` and CI skip `plans/`;
  lint-staged checks every staged Markdown file, plans included.
- **fallow**: audits the frontend for dead code, duplication, and complexity, from the
  entry points in `.fallowrc.json`. It runs on every commit and in CI against the base
  branch.
- **Husky**: installs the git hooks in `.husky/`: pre-commit runs lint-staged and the
  fallow audit, and pre-push runs the production build.
- **lint-staged**: runs the fixers and checks listed in `package.json` on the staged
  files only, by file type: ESLint and Prettier for TypeScript; Ruff, pydoclint, and
  the function-length check for Python; markdownlint and Prettier for Markdown.
- **npm-run-all2**: provides `run-p`, which `npm test` uses to run the frontend and
  backend suites in parallel.

## Containers and images

- **Docker Engine**: runs the database, backend, and frontend as containers in
  development and on the production server, so the backend runs the same image and
  entrypoint in both. `scripts/provision.sh` installs it from Docker's own apt
  repository, with its CLI, containerd, and the Buildx and Compose plugins.
- **Docker Compose**: defines the stacks. `docker-compose.yml` is the development
  stack and the base for production; `docker/docker-compose.prod.yml` swaps the
  frontend for the nginx image, binds the backend and frontend to loopback ports for
  host nginx, and stops publishing the database port. Its `!reset` and `!override`
  tags need Compose 2.24.4 or newer.
- **Docker Buildx**: Docker's BuildKit build plugin. `docker/nginx.Dockerfile` relies
  on BuildKit's `$BUILDPLATFORM` to run its Node stage on the build machine's
  platform.
- **`python:3.12-slim`**: the backend image base. It installs only `requirements.txt`,
  so the image carries no lint, type-check, or test tools.
- **`node:22-slim`**: the development frontend image, which runs the Vite dev server,
  and the build stage of the production frontend image.
- **`nginx:1.27-alpine`**: the production frontend image. `docker/nginx.conf` serves
  the built bundle, falls back to `index.html` for client routes, proxies `/api` and
  `/uploads` to the backend, and answers oversized uploads with the app's JSON 413.
- **`postgres:16`**: the database image, with a `pg_isready` health check the backend
  waits on before it starts. CI runs the same image as a service container.
- **`alpine`**: the throwaway container `scripts/backup.sh` mounts the uploads volume
  into to archive it; the restore steps in `ai/backups.md` use it the same way.

## GitHub

- **GitHub Actions**: CI, in `.github/workflows/ci.yml`, on every push and pull
  request. Its four jobs cover the backend (Ruff, pydoclint, the function-length
  check, basedpyright, and pytest against a PostgreSQL service), the fallow audit
  against the base branch, the frontend (ESLint, Prettier, markdownlint, and Vitest),
  and the production build. `assign-issues.yml` assigns each new issue to the
  repository owner through `actions/github-script`.
- **Reusable actions**: `actions/checkout`, `actions/setup-python` with a pip cache
  keyed on both requirements files, `actions/setup-node` with the npm cache, and
  `actions/github-script`.
- **GitHub CLI (`gh`)**: the Claude Code hook `scripts/hook-issue-assign.sh` uses it to
  assign an issue created with `gh issue create` to the repository owner.
- **Issue forms**: `.github/ISSUE_TEMPLATE/` provides bug and feature forms, which
  apply the `bug` or `enhancement` label and assign the owner, and disables blank
  issues.

## Servers and operations

The server's packages come from `scripts/provision.sh` and `scripts/install-backup.sh`;
`scripts/deploy.sh` installs the nginx site, the renewal hook, and the monitoring units.

- **Ubuntu**: the production server's operating system. `scripts/provision.sh`
  installs every package with apt.
- **Host nginx**: the reverse proxy in front of the stack. The site rendered from
  `scripts/nginx-ssl.conf.template` redirects HTTP to HTTPS, terminates TLS, and
  proxies to the loopback ports Compose publishes; every deploy rewrites it. nginx
  arrives as a dependency of `python3-certbot-nginx`.
- **Certbot and Let's Encrypt**: issue and renew the certificate. The first issuance
  uses the standalone authenticator; the renewal config is then switched to the nginx
  authenticator from `python3-certbot-nginx`, because standalone cannot bind port 80
  while nginx holds it. The packaged `certbot.timer` attempts renewal twice a day, and
  a deploy hook reloads nginx after each renewal. See `ai/tls.md`.
- **systemd**: the units and timers under `scripts/systemd/`: the nightly backup at
  02:30 UTC, the daily certificate expiry check at 05:00 UTC, and the `OnFailure`
  drop-in that reports a failed certbot renewal. The scripts render their
  `__APP_NAME__` and `__REPO_DIR__` placeholders so several apps can share a host.
- **rclone**: pushes the backups to an S3-compatible bucket, DigitalOcean Spaces by
  default, with tiered daily, weekly, and monthly retention.
  `scripts/install-backup.sh` installs it and writes its remote from `.env`.
- **pg_dump and pg_restore**: run inside the database container. Every backup, and
  the dump each deploy takes before migrating, is a custom-format `pg_dump`; the
  manual recovery in `ai/backups.md` restores one with `pg_restore`.
- **OpenSSL**: generates the database password and Flask's secret key when a server is
  provisioned, and reads certificate expiry dates in `scripts/cert-check.sh`.
- **curl**: fetches Docker's apt signing key, asks `api.ipify.org` for the server's
  public address before certbot runs, waits for the backend's health endpoint during
  deploys, and delivers alerts to the webhook.
- **dig**: from `dnsutils`. It confirms the domain resolves to the server's address
  before certbot asks for a certificate.
- **Webhooks (ntfy.sh, Slack, or Discord)**: where `scripts/alert.sh` sends failed
  backups, failed renewals, and expiring certificates. `ALERT_WEBHOOK_FORMAT` picks
  the payload shape, and the server's `python3` escapes the Slack and Discord JSON.
  With no URL set, alerts are only logged.
- **git**: the server runs from a clone of the repository, and every deploy pulls into
  it.
- **Vim**: the editor for reviewing the generated `.env` on the server and filling in
  values such as the `SPACES_*` credentials.
- **ca-certificates**: the root certificates apt and curl check HTTPS against, which
  Docker's apt repository and signing key need.
- **SSH**: `npm run deploy` runs `scripts/deploy.sh` on the server over SSH, through
  `scripts/remote-deploy.sh`.
- **lsof**: finds free host ports. `scripts/up.sh` moves a busy port to the next free
  one before it starts the dev stack, and `scripts/worktree-setup.sh` skips offsets
  whose ports are in use.

## Editor and agent setup

- **EditorConfig**: `.editorconfig` sets UTF-8, LF, 4-space indentation (2 for JSON
  and YAML), a 90-character line limit, and trailing-whitespace and final-newline
  rules, so any editor matches Prettier and Ruff.
- **VS Code**: `.vscode/settings.json` formats on save with Prettier, or Ruff for
  Python, points the Python extension at `.venv`, runs pytest without coverage so a
  single test can run, and points TypeScript at the project's own copy.
  `.vscode/launch.json` debugs Flask, selected Python tests, and the current Vitest
  file. `.vscode/extensions.json` recommends the extensions for the stack: Python,
  Pylance, and the debugger; the Vitest explorer; Ruff; ESLint; Prettier; GitHub Pull
  Requests and GitHub Actions; Docker and Dev Containers; markdownlint; YAML; Even
  Better TOML; EditorConfig; Code Spell Checker; Error Lens; Pretty TypeScript Errors;
  ShellCheck; fallow; npm Intellisense; Claude Code; and Open in GitHub. It marks the
  Jest and legacy Test Explorer extensions unwanted.
- **Dev Containers**: `.devcontainer/devcontainer.json` starts from Microsoft's Python
  3.12 dev container image, adds Node 22 and Docker-in-Docker, fills `.venv` from
  `requirements-dev.txt`, installs `node_modules`, and forwards the Flask and Vite
  ports, so a fresh machine gets the whole toolchain.
- **ShellCheck**: runs in the editor through its extension; two scripts carry
  `# shellcheck` directives where its warnings do not apply. CI does not check the
  shell scripts.
- **Claude Code**: `.claude/settings.json` pre-approves the project's npm, npx, venv,
  and Compose commands and adds two hooks, both reading their input with jq: `tsc -b`
  after every TypeScript edit, and `scripts/hook-issue-assign.sh`, which assigns an
  issue created with `gh` to the repository owner. `.claude/CLAUDE.md` and `AGENTS.md`
  point agents at the canonical instructions under `ai/`.
- **Git worktrees**: `scripts/worktree-setup.sh` supports a bare-repo layout with one
  worktree per branch, each with its own `.env`, Compose project, shifted ports,
  `.venv`, and `node_modules`, so several branches can run side by side.
```

### `requirements-dev.txt` — remove pytest-flask

Delete line 8, `pytest-flask==1.3.0`, and nothing else. The file becomes:

```text
# Development and CI tools on top of the runtime packages. The backend image never
# installs this file; every tool runs from .venv, locally and in CI.
-r requirements.txt
ruff==0.9.10
pydoclint==0.9.1
basedpyright==1.39.9
pytest==8.3.5
pytest-cov==6.1.0
```

### `README.md` — link after the Stack table

The Stack table ends at line 16, and line 17 is blank. After line 17, insert this line
and a blank line, so `## Quick start (local, no Docker)` moves from line 18 to 20:

```markdown
[`tools.md`](tools.md) says why each tool and library in the repository is here.
```

It is the README's first Markdown link; elsewhere the README names docs as backticked
paths (`README.md:179-183`). The issue asks for a link, and GitHub renders this one.

### `ai/project.md` — list it under Project Structure

After line 32, the second line of the `scripts/` entry, add:

```markdown
- `tools.md` - why each tool and library is in the repository
```

It follows the list's `path - description` form, with a backticked path like every
other entry in the file.

## Parallelism

- **In parallel, sharing no files**: A `tools.md`; B `requirements-dev.txt`; C
  `README.md` and `ai/project.md`.
- **After B**: Verification step 1, which removes the plugin from `.venv` so the local
  suite runs the way CI's fresh install will.
- **After A to C**: Verification steps 2 to 5, with step 4's three commands in one
  parallel batch.

## No other changes needed

- `pyproject.toml`, `src_back/tests/conftest.py`, and the tests: nothing configures or
  calls pytest-flask. Outside `requirements-dev.txt:8`, only
  `plans/archive/pr-38-keep-development-tools-out-of-the.md:7,91` names it, and the
  archive stays as history.
- `package.json`, `.markdownlint.json`, and `.prettierignore`: `npm run lint:md`
  already covers `**/*.md` outside `plans/` (`package.json:16`), and `.prettierignore`
  does not exclude root Markdown, so both check `tools.md` with no configuration
  change.
- `AGENTS.md` and `.claude/CLAUDE.md`: the issue asks only for the README and
  `ai/project.md`, and `.claude/CLAUDE.md` imports `ai/project.md`, so agents see the
  new entry.
- CI: `cache-dependency-path: requirements*.txt` (`.github/workflows/ci.yml:36`)
  re-keys the pip cache when `requirements-dev.txt` changes.
- Noticed, out of scope:
    - `@testing-library/dom` is a required peer of `@testing-library/react` and
      `@testing-library/user-event`. npm installs it on its own
      (`package-lock.json:2262-2268`, `"peer": true`), but `package.json` does not
      declare it.
    - `vite.config.ts:55` declares an `@` alias that nothing imports, and
      `.fallowrc.json:12` ignores `src_front/src/styles/**`, which does not exist.
    - `@types/node` is `^25.9.1` while every runtime pin is Node 22.

## Verification

1. **Match `.venv` to the new dev file.** pip does not remove a package that leaves a
   requirements file, so uninstall it and confirm pytest no longer loads it:

    ```bash
    .venv/bin/pip uninstall -y pytest-flask
    .venv/bin/python -m pytest --co --no-cov | grep '^plugins:'
    ```

    It must print `plugins: cov-6.1.0`.

2. **Every pin, package, and installed server tool has an entry**, and pytest-flask is
   gone:

    ```bash
    { grep -hvE '^[[:space:]]*(#|-r|$)' requirements*.txt | cut -d= -f1
      jq -r '.dependencies + .devDependencies | keys[]' package.json
      printf '%s\n' Docker Buildx Compose nginx Certbot rclone systemd
    } | while read -r n; do grep -qiF -- "$n" tools.md || echo "missing: $n"; done
    grep -n 'pytest-flask' tools.md requirements-dev.txt
    ```

    Both commands must print nothing. The loop matches substrings, so also read each
    section against the inventory in Context.

3. **The issue's acceptance gates**: `npm run lint:md` and `npx prettier --check .`.
4. **Full gates**, in one parallel batch: `npm run test`, `npm run lint`, and
   `npm run lint:py`. The backend half of `npm run test` proves the suite and its 100%
   coverage gate hold without pytest-flask.
5. Open `README.md` in VS Code's Markdown preview and follow the new link to
   `tools.md`.
