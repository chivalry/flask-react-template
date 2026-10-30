# Tools and Libraries

Why each tool and library in this repository is here, one short entry apiece. The
pinned versions live in `requirements.txt`, `requirements-dev.txt`, and `package.json`,
apart from watchdog's in `docker-compose.override.yml`; the server-side tools are
installed by the scripts under `scripts/` and the images under `docker/`.
`ai/project.md` describes the repository's own scripts and commands, and the runbooks
`ai/backups.md` and `ai/tls.md` describe how the operations tools are used. This file
only explains what each one is for.

## Languages and runtimes

- **Python 3.12**: the backend language, and the oldest version the code runs on: it
  uses PEP 695 generics, which arrived in 3.12. The backend image is
  `python:3.12-slim`, CI and the dev container install 3.12, and `pyproject.toml` makes
  it Ruff's target and basedpyright's Python version. Local work runs through
  `.venv/bin/`, a virtual environment filled by pip from `requirements-dev.txt`, never
  through the system interpreter.
- **Node.js 22 and npm**: run the frontend toolchain: Vite, Vitest, ESLint, Prettier,
  and the rest of `package.json`. The frontend images build on `node:22-slim`, CI and
  the dev container pin 22, `.node-version` asks version managers such as fnm for 22,
  and `npm ci` installs exactly what `package-lock.json` records.
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

Installed from `requirements.txt` into the backend image and into `.venv`, except
watchdog, which only the dev stack's backend image gets, and the standard-library
modules in the last entry, which come with Python.

- **Flask**: the web framework. `src_back/app.py` builds the app through a factory,
  registers one blueprint per domain, maps exceptions to JSON error envelopes, and
  serves the built SPA and the login-protected uploads. Its `flask` command applies
  the migrations and runs the development server, on the host and in the dev stack.
- **Werkzeug**: Flask's underlying WSGI toolkit, installed with Flask rather than
  pinned on its own. The code uses it directly for password hashing in
  `src_back/models/user.py`, for the `NotFound` exception the SPA fallback catches
  when no build is present, and for the `FileStorage` type and `safe_join` in the
  upload helpers.
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
  unauthorized handler makes it answer a JSON 401 instead of redirecting. Every sign-in
  goes through `complete_login()`, which makes the session permanent, so a sign-in
  lasts 30 days past its latest request.
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
  command, the seed, and pytest read the same settings on the host;
  `python -m src_back.mailer`, which never imports the app, loads it itself. In the
  containers Compose supplies the variables instead, and `.dockerignore` keeps `.env`
  out of the image.
- **gunicorn**: the production WSGI server. `docker/entrypoint.sh` starts it after the
  migrations and the seed whenever `FLASK_ENV` is not `development`, with
  `GUNICORN_WORKERS` workers: 2 by default, 4 in the production override. The dev stack
  and work without Docker use Flask's development server.
- **watchdog**: not in `requirements.txt`; the dev stack's build installs it into the
  backend image through the `DEVELOPMENT_PACKAGES` build argument. Flask's reloader uses
  it when present and then notices modules being added and deleted, which its fallback
  stat reloader misses.
- **`smtplib` and `email`**: the standard-library modules `src_back/mailer.py` sends
  mail with. No mail package is installed: these work with any provider that speaks
  SMTP, while a vendor SDK, such as SendGrid's, would tie the app to one.

## Backend quality and test tools

Installed from `requirements-dev.txt` into `.venv` only; the backend image never has
them. `npm run lint:py` and `npm run test:back` run them, as do lint-staged and CI,
except pip-audit, which only CI and a manual run use.

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
- **pip-audit**: checks the packages in `requirements.txt`, and those they pull in,
  against PyPI's vulnerability data. CI's backend job fails on any known vulnerability;
  run it locally with `.venv/bin/pip-audit -r requirements.txt`.

## Frontend runtime libraries

The `dependencies` in `package.json`: what the browser bundle ships.

- **React 19 and react-dom**: the UI library and its DOM renderer. `main.tsx` mounts
  the app under `StrictMode` inside an error boundary and the theme and router
  providers, and `App.tsx` loads each page with `React.lazy`, so every page ships in
  its own chunk.
- **MUI (`@mui/material`)**: the component library: the app bar, the sign-in and
  registration forms, the alerts, and the theme in `theme.ts`.
- **`@mui/icons-material`**: MUI's icon set: the app bar's navigation and logout icons,
  and the add, edit, and delete buttons of record lists.
- **Emotion (`@emotion/react`, `@emotion/styled`)**: MUI's styling engine. MUI requires
  both as peer dependencies even though no source file imports them, which is why
  `.fallowrc.json` tells fallow to ignore them.
- **Axios**: the HTTP client. `api/client.ts` sets `baseURL: '/api'` and
  `withCredentials`, and its interceptors copy the server's error text onto the error
  and tell the auth store about a 401.
- **TanStack Query (`@tanstack/react-query`)**: server state. `main.tsx` provides one
  `QueryClient`; each resource's hooks module wraps `useQuery` and
  `useResourceMutations` (`hooks/resources.ts`), which invalidates the cached lists
  after a change, and `useSessionQueryCache` clears the cache when the signed-in
  account changes. `vite.config.ts` puts it in the `react` vendor chunk.
- **React Router (`react-router-dom`)**: client-side routing. `App.tsx` holds the
  route table, and `ProtectedRoute` sends a signed-out visitor to the login page.
- **React Hook Form (`react-hook-form`)**: form state and validation for the sign-in
  and registration forms and for every `FormDialog`, whose `FormTextField`,
  `FormSelectField`, and `FormSwitchField` bind to it.
- **`@hookform/resolvers`**: the bridge that lets React Hook Form validate with the
  Zod schemas.
- **Zod**: the sign-in, registration, and account form schemas (`schemas/`), which also
  type the form values, so the frontend checks the backend's rules before a request is
  sent.
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
  which `vite.config.ts` and `test/globalSetup.ts` use, and for React and react-dom,
  which ship none of their own.
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
  lint-staged checks every staged Markdown file, plans included. `package.json`
  overrides its `re2js` dependency to 2.8.7: markdownlint pins 2.8.6 exactly, a version
  with a high-severity advisory (GHSA-gg6h-894w-4m9c) that fails CI's `npm audit`. Drop
  the override once a markdownlint release pins 2.8.7 or later.
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

## Shell script tests

`npm run test:scripts` runs `scripts/tests/run-all.sh`, and so does CI.

- **`scripts/tests/`**: Bash tests. Each `test-<script>.sh` runs its script against
  stub commands such as `docker`, `lsof`, `rclone`, `systemctl`, and `sudo`, which log
  their calls instead of acting, and checks the log and the files the script wrote;
  `test-compose-config.sh` checks the rendered Compose stacks instead, and
  `test-nginx-site.sh` and `test-backend-image.sh` run real containers. `run-all.sh`
  first checks every script's syntax with `bash -n` or `sh -n`, as its shebang names.
- **jq**: `test-compose-config.sh` queries the JSON that `docker compose config`
  renders for each stack with it. The CI runner has it; locally, the test skips
  without it or without the docker CLI.
- **Docker daemon, curl, and openssl**: `test-nginx-site.sh` runs the host site template,
  rendered for three apps, one behind basic auth, in `nginx:1.27-alpine` with throwaway
  certificates and sends it requests with curl; `test-backend-image.sh` builds the
  backend image and runs it beside `alpine`. The CI runner has all three; locally, each
  test skips without them.

## Containers and images

- **Docker Engine**: runs the database, backend, and frontend as containers in
  development and on the production server, so the backend builds from the same
  Dockerfile and runs the same entrypoint in both. `scripts/provision.sh` installs it
  from Docker's own apt repository, with its CLI, containerd, and the Buildx and
  Compose plugins.
- **Docker Compose**: defines the stacks. `docker-compose.yml` is the development
  stack and the base for production. `docker-compose.override.yml`, which Compose loads
  only when no `-f` is given, adds the development file watch that syncs edits into the
  running containers; `npm run docker:up` watches through `up --watch`, which needs
  Compose 2.24.7 or newer. `docker/docker-compose.prod.yml` swaps the frontend for the
  nginx image, binds the backend and frontend to loopback ports for host nginx, and
  stops publishing the database port. Its `!reset` and `!override` tags need Compose
  2.24.4 or newer.
- **Docker Buildx**: Docker's BuildKit build plugin. `docker/nginx.Dockerfile` relies
  on BuildKit's `$BUILDPLATFORM` to run its Node stage on the build machine's
  platform.
- **`python:3.12-slim`**: the backend image base. It installs only `requirements.txt`,
  plus watchdog when the dev stack builds it, so the image carries no lint, type-check,
  or test tools. It runs the app as the unprivileged `app` user, uid 10001.
- **`node:22-slim`**: the development frontend image, which runs the Vite dev server,
  and the build stage of the production frontend image.
- **`nginx:1.27-alpine`**: the production frontend image. `docker/nginx.conf` serves
  the built bundle, falls back to `index.html` for client routes, proxies `/api` and
  `/uploads` to the backend, and answers oversized uploads with the app's JSON 413.
  Host nginx sits in front of it and sends the security headers, so it adds none.
  `test-nginx-site.sh` runs the host site in this image too.
- **`postgres:16`**: the database image, with a `pg_isready` health check the backend
  waits on before it starts. CI runs the same image as a service container. The weekly
  restore drill restores the newest backup into a scratch container of the same image,
  and `test-restore-drill.sh` checks that the drill and the `db` service name the same
  tag.
- **`alpine`**: the throwaway container `scripts/backup.sh` mounts the uploads volume
  into to archive it; the restore steps in `ai/backups.md` use it the same way.
  `scripts/deploy.sh` uses it to hand the uploads volume to the backend's user,
  `scripts/copy-production.sh` to copy production's uploads volume into staging's, and
  `test-backend-image.sh` to stand in for an old volume.

## GitHub

- **GitHub Actions**: CI, in `.github/workflows/ci.yml`, on every push and pull
  request, and on demand from the Actions tab. Its five jobs cover the backend (Ruff,
  pydoclint, the function-length check, basedpyright, pytest against a PostgreSQL service,
  and pip-audit), the fallow audit against the base branch, the frontend (ESLint,
  Prettier, markdownlint, Vitest, and `npm audit` at high severity), the production build,
  and the shell scripts (syntax checks and `scripts/tests/`). `assign-issues.yml` assigns
  each new issue to the repository owner through `actions/github-script`.
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
`scripts/deploy.sh` installs the nginx site and, in production only, the renewal hook
and the monitoring, backup, and restore-drill units.

- **Ubuntu**: the production server's operating system. `scripts/provision.sh`
  installs every package with apt.
- **Host nginx**: the reverse proxy in front of the stack. The site rendered from
  `scripts/nginx-ssl.conf.template` redirects HTTP to HTTPS, terminates TLS, sends the
  security headers, asks for a password when `STAGING_HTPASSWD` is set, throttles
  sign-in POSTs, and proxies to the loopback ports Compose publishes; every deploy
  rewrites it. nginx arrives as a dependency of `python3-certbot-nginx`.
- **Certbot and Let's Encrypt**: issue and renew the certificates. The first issuance
  on a bare host uses the standalone authenticator, and its renewal config is then
  switched to the nginx authenticator from `python3-certbot-nginx`, because standalone
  cannot bind port 80 while nginx holds it. A later issuance goes through the running
  nginx. The packaged `certbot.timer` attempts renewal twice a day, and a deploy hook
  reloads nginx after each renewal. See `ai/tls.md`.
- **systemd**: the units and timers under `scripts/systemd/`: the nightly backup at
  02:30 UTC, the weekly restore drill on Sundays at 04:00 UTC, the daily certificate
  expiry check at 05:00 UTC, and the units that `OnFailure=` starts to report a failed
  certbot renewal and a failed or timed-out drill. A production deploy installs them
  all, and `scripts/install-backup.sh` installs the backup and drill units too. The
  scripts render their `__APP_NAME__` and `__REPO_DIR__` placeholders so several apps
  can share a host.
- **rclone**: once a bucket is configured, pushes the backups to an S3-compatible
  bucket, DigitalOcean Spaces by default, with tiered daily, weekly, and monthly
  retention, and the restore drill fetches the newest dump and the uploads archive of
  the same run from it. `scripts/install-backup.sh` installs it and writes its remote
  from `.env`.
- **pg_dump and pg_restore**: run inside the database container. Every backup is a
  custom-format `pg_dump`, as is the dump each production deploy takes before migrating,
  which is named for the commit that was running. The manual recovery in
  `ai/backups.md` restores one with `pg_restore`, and the restore drill restores the
  newest daily dump into a scratch container every week. `scripts/copy-production.sh`
  pipes a `pg_dump` of production's database into staging's database container, where
  `pg_restore` turns it into SQL that `psql` runs in one transaction.
- **OpenSSL**: generates the database password and Flask's secret key when a server is
  provisioned, hashes the password in staging's nginx password file with
  `openssl passwd -6` (`ai/staging.md`), and reads certificate expiry dates in
  `scripts/cert-check.sh`.
- **curl**: fetches Docker's apt signing key, asks `api.ipify.org` for the server's
  public address before certbot runs, waits for the backend's health endpoint during
  deploys, and delivers alerts to the webhook.
- **dig**: from `dnsutils`. It confirms the domain resolves to the server's address
  before certbot asks for a certificate.
- **Webhooks (ntfy.sh, Slack, or Discord)**: where `scripts/alert.sh` sends failed
  backups, failed restore drills, failed renewals, and expiring certificates.
  `ALERT_WEBHOOK_FORMAT` picks the payload shape, and the server's `python3` escapes
  the Slack and Discord JSON. With no URL set, alerts are only logged.
- **git**: the server runs from a clone of the repository, and every deploy first
  checks that the clone is on `DEPLOY_BRANCH`, then pulls into it.
- **Vim**: the editor for reviewing the generated `.env` on the server and filling in
  values such as the `SPACES_*` credentials.
- **ca-certificates**: the root certificates apt and curl check HTTPS against, which
  Docker's apt repository and signing key need.
- **SSH**: `npm run deploy` and `npm run deploy:staging` run `scripts/deploy.sh` on the
  server over SSH, through `scripts/remote-deploy.sh`, in the production or the staging
  clone.
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
  `# shellcheck` directives where its warnings do not apply. CI does not run it; its
  shell-script job checks syntax with `bash -n` and `sh -n` and runs `scripts/tests/`.
- **Claude Code**: `.claude/settings.json` pre-approves the project's npm, npx, venv,
  and Compose commands and adds two hooks, both reading their input with jq: `tsc -b`
  after every TypeScript edit, and `scripts/hook-issue-assign.sh`, which assigns an
  issue created with `gh` to the repository owner. `.claude/CLAUDE.md` and `AGENTS.md`
  point agents at the canonical instructions under `ai/`.
- **Git worktrees**: `scripts/worktree-setup.sh` supports a bare-repo layout with one
  worktree per branch, each with its own `.env`, Compose project, shifted ports,
  `.venv`, and `node_modules`, so several branches can run side by side.
