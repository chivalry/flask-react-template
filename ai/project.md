# Project Instructions

Replace this paragraph with the project's name and purpose when starting a project from
this template. The sections describe the layout, the commands, and the database rules
that every contributor and agent follows.

## Project Structure

- Backend: `src_back/` - Python/Flask
    - `api/` - Flask route handlers, one blueprint per domain
    - `jobs/` - scheduled jobs, one module each, which `python -m src_back.jobs.<name>`
      runs once; `example.py` is the one to copy (Scheduled Jobs, below)
    - `models/` - SQLAlchemy models, one module per domain; `base.py` holds
      `BaseMixin`, `user.py` holds `Role` and `User`, `audit_log.py` holds `AuditAction`
      and `AuditLog`, and `__init__.py` re-exports every model, so
      `from src_back.models import User` works and every table registers
    - `schemas/` - Marshmallow schemas; `schemas/base.py` holds `BaseSchema` and
      `validate_ids_exist()`
    - `services/` - business logic by domain; `services/base.py` holds the generic
      `CRUDService`, `ChildRecordService`, and `require_unique_name()`,
      `services/errors.py` the exceptions services raise, `services/audit_log.py` the
      audit trail and the history queries, and `services/users.py` the admin's account
      management
    - `tests/` - pytest; one `test_<module>.py` per module; `helpers.py` holds
      `persist()`
    - `app.py` - application factory, error handlers, SPA and upload serving
    - `auth.py` - `current_user` typed as `User`, for routes behind `@login_required`
    - `extensions.py` - shared Flask extensions and the declarative `Base`
    - `mailer.py` - plain-text email through the SMTP account in `SMTP_*`, standard
      library only; off while `SMTP_HOST` is blank
    - `seed.py` - the seed every container start runs; it creates the first admin
    - `utils.py` - error envelopes, pagination in memory and in SQL, query-string
      parsing, quote folding, upload validation
- Frontend: `src_front/src/` - React/TypeScript with Vite
    - `api/` - axios client, the `resource()` factory, and typed API modules
    - `components/` - React components; `components/layout/` holds `AppShell.tsx`, the
      shell, and the master-detail layout (`MasterDetailLayout`, `ListPaneHeader`,
      `ChildPortal`); `components/common/` holds the form, record-list, and detail
      kit; and `components/admin/` the admin screens and `UsersMasterDetail`, the
      example an admin sees on Home
    - `hooks/` - shared hooks, including the TanStack Query hooks for each resource
    - `pages/` - top-level page components
    - `schemas/` - Zod form schemas, their defaults, and their payload mappers
    - `store/` - Zustand stores
    - `types/` - TypeScript types shared across modules
    - `utils/` - framework-free helpers, such as local-day dates, record counts, and
      account descriptions
    - `test/` - Vitest tests mirroring `src/`; `test/utils/` holds the shared helpers
- `ai/` - these instructions; `AGENTS.md` and `.claude/CLAUDE.md` point here
- `docker/` - Dockerfiles, entrypoint, job loop, nginx config, production Compose override
- `migrations/` - Alembic migrations
- `plans/` - implementation plans; authoritative while a feature is in progress
- `scripts/` - local tooling (ports, worktrees) and server provisioning, deployment
  (production and staging), TLS, and backup scripts; `scripts/systemd/` holds the units
  and timers a production deploy installs, and `scripts/tests/` the shell-script tests
  and `run-all.sh`, which checks every script's syntax and then runs them
- `tools.md` - why each tool and library is in the repository

## Commands

All commands run from the repo root via npm scripts. Python tooling always goes through
`.venv/bin/`, installed from `requirements-dev.txt`; `requirements.txt` holds only the
runtime packages and is the file `docker/backend.Dockerfile` installs, adding `watchdog`
for the reloader only when the dev stack builds it.

- `npm run test` - frontend and backend suites in parallel, both with coverage
- `npm run test:back` - `.venv/bin/python -m pytest` (100% coverage enforced)
- `npm run test:front` - `vitest run --coverage` (100% thresholds)
- `npm run test:scripts` - `bash -n` or `sh -n` on every shell script by its shebang,
  then `scripts/tests/test-*.sh`, through `scripts/tests/run-all.sh`, which CI runs too
- `npm run lint` - ESLint; CI adds `--max-warnings=0`
- `npm run lint:py` - Ruff check and format check, pydoclint, function length,
  basedpyright
- `npm run lint:md` - markdownlint
- `npm run typecheck` - `tsc -b`
- `npm run format` and `npm run format:py` - Prettier and Ruff format
- `npm run fallow` - duplication and dead-code audit of the frontend
- `npm run docker:up` - build and start the dev stack, assigning free ports into `.env`,
  then watch it (`develop.watch` in `docker-compose.override.yml`) so saved edits reach
  the running containers. It stays attached, so an agent runs it as a background
  command; `npm run docker:up -- -d` starts detached and does not watch
- `npm run docker:url` - wait for the dev frontend and print its URL
- `npm run docker:seed` - run the seed inside the backend container
- `npm run docker:down` - stop the dev stack
- `npm run deploy` - deploy production over SSH (`DEPLOY_HOST` or an argument)
- `npm run deploy:staging` - deploy the staging clone the same way (`ai/staging.md`)

## Database

- PostgreSQL 16 in Docker and production. Tests use in-memory SQLite; CI also runs
  them against PostgreSQL through `TEST_DATABASE_URL`.
- SQLAlchemy 2.x: models subclass `Base` from `extensions.py` and use `Mapped[]` with
  `mapped_column`. Every model mixes in `BaseMixin` (`id`, `uuid`, `created_at`,
  `updated_at`).
- Queries go through `db.session` (`db.session.get`, `db.session.query`); there is no
  `Model.query`.
- Migrations use Flask-Migrate/Alembic. Author with
  `.venv/bin/flask --app src_back.app db migrate -m "<slug>"`, review the file, apply
  with `db upgrade`, and confirm with `db check`, which must report that no new upgrade
  operations were detected. Files are named `YYYY_MM_DD_<rev>_<slug>.py`.
- Every foreign key declares `ondelete`, and a parent's collection of child rows also
  sets `cascade='all, delete-orphan'`. The SQLite test database does not enforce
  foreign keys, so only the ORM cascade makes a delete there behave as it does on
  PostgreSQL.
- `docker/entrypoint.sh` owns migrations: it runs `db upgrade` and the seed on every
  container start, in development and in production, and a non-zero exit stops the
  container. Seeds skip optional work themselves instead of failing. It then starts
  gunicorn, or, under `FLASK_ENV=development`, Flask's development server with the
  reloader and without the debugger; the dev build installs `watchdog`, so the reloader
  also sees added and deleted modules. The dev stack syncs `migrations/` into the
  backend without restarting its container, so a generated revision is applied by
  `db upgrade` or at the next backend start, never by the sync. `scripts/deploy.sh`
  never runs `db upgrade` itself; it takes a database backup in production, restarts
  the stack, and waits for `/api/health`, which the backend serves only after the
  entrypoint finishes. This assumes one backend container; scaling it out means moving
  migrations into the deploy step.
- Run `flask` inside the container or through the venv, never with the system Python:
  `docker compose exec -T backend flask --app src_back.app db upgrade` or
  `.venv/bin/flask --app src_back.app ...`.
- `.env` points `DATABASE_URL` at `localhost:$DB_PORT` for host-side commands; inside
  Compose the backend uses the `db` hostname.

## Environment

`.env.example` documents every variable. `scripts/up.sh` rewrites the port variables,
and `PUBLIC_BASE_URL` with them, when a port is busy; `scripts/worktree-setup.sh` shifts
them per worktree. Outside `FLASK_ENV=development`, the app refuses to start with a
placeholder `SECRET_KEY`, and without `PUBLIC_BASE_URL` it starts with OAuth sign-in
and passkeys disabled. The seed creates the first admin from `ADMIN_EMAIL` and
`ADMIN_PASSWORD` when both are set, no admin exists yet, and no account has that email,
and never changes an existing account; `scripts/provision.sh` generates `ADMIN_PASSWORD`
and leaves `ADMIN_EMAIL` blank to fill in before the first deploy.

`.env.staging.example` is a whole staging `.env` (`ai/staging.md`). `APP_ENVIRONMENT`
names the deployment, production when blank. `/api/health` reports it, the frontend
badges every page outside production, and any other environment names its own session
cookie. `DEPLOY_BRANCH` is the branch a server clone must be on.

Mail is off until `SMTP_HOST` is set: `smtp_settings_from_environment()` in
`src_back/mailer.py` returns `None` while it is blank, and code that sends mail then
skips it. `SMTP_SECURITY` is `starttls` (the default, port 587), `ssl` (465), or `none`,
and `SMTP_PORT` overrides the port. The sender is `SMTP_FROM`, or `SMTP_USERNAME` when
that is blank, and must be an email address. `send_email()` sends one plain-text
message and raises `EmailDeliveryError` when the server refuses it or cannot be reached.
Staging keeps `SMTP_HOST` blank, because its accounts are copies of production's, and a
server provisioned before the mailer has no `SMTP_*` lines in its `.env`, which leaves
mail off there until they are added. To check the settings, send a test message.
Compose hands `.env`'s values to a container only when it creates one, so on a server,
redeploy (`npm run deploy`) after changing `SMTP_*`, then run it in the backend
container:

```bash
.venv/bin/python -m src_back.mailer you@example.com      # locally, reading .env
docker compose -f docker-compose.yml -f docker/docker-compose.prod.yml --env-file .env \
  exec -T backend python -m src_back.mailer you@example.com   # on a server
```

`src_back/app.py` calls `load_dotenv()` at import, so `.env` values are visible to pytest
too. A test that depends on an environment variable sets or clears it with
`monkeypatch` first, as the `FLASK_ENV` and `CORS_ALLOWED_ORIGINS` tests in
`src_back/tests/test_app.py` do; `conftest.py` clears `APP_ENVIRONMENT` and the `SMTP_*`
variables for every test, so no test sends mail through a developer's account.

## Scheduled Jobs

A scheduled job is a module in `src_back/jobs/` that `python -m src_back.jobs.<name>`
runs once. Its `main(app=None)` builds the app with `create_app()` unless a test passes
one, does its work inside one application context, commits, prints one line saying
what it did, and returns the exit status, which its `__main__` block raises as
`SystemExit`. An exception exits 1 with its traceback. Print rather than log: the app
installs no logging handler, so `logging` drops everything below a warning.
`src_back/jobs/example.py`, which counts the active accounts and changes nothing, is the
one to copy, and `src_back/tests/test_example_job.py` calls its `main()` with the `app`
fixture.

A job must be safe to run again: a timer catches up a run the server missed, anyone can
start one by hand, and a run can fail partway. Record what is done in the data, such as
a column stamped when a row is handled, and commit right after each outside effect, such
as an email, so a failure later in the run neither repeats the effect nor loses the
record of it. Keep times timezone-aware, as `datetime.now(UTC)` is.

Run a job once:

```bash
docker compose exec -T backend python -m src_back.jobs.example  # in the dev stack
.venv/bin/python -m src_back.jobs.example                       # locally, reading .env
docker compose -f docker-compose.yml -f docker/docker-compose.prod.yml --env-file .env \
  exec -T backend python -m src_back.jobs.example               # a server, staging too
systemctl start $APP_NAME-job@example.service                   # production's unit
```

A production deploy installs three templates from `scripts/systemd/`. An instance of
`$APP_NAME-job@.service` runs the job it is named for in the running backend container,
with the backend's environment:
`docker compose ... exec -T backend timeout 1h python -u -m src_back.jobs.<name>`.
`-u` keeps the output unbuffered, so the journal holds what a run printed even when
`timeout` stops it. `$APP_NAME-job@.timer` starts it daily at 03:00 UTC, half an hour
after the backup starts its dump, and catches up a run the server was off for.
`$APP_NAME-alert-job@.service` reports a run that exits non-zero or outlasts its hour
through `scripts/alert.sh`. The hour is enforced inside the container, because stopping
`docker compose exec` leaves its process running there (moby/moby#9098); the unit's
`TimeoutStartSec=` stops a docker CLI that hangs. A failed run is not retried; once the
cause is fixed, start the service by hand. A catch-up run after a boot can start before
the stack is up, fail, and alert once, as a catch-up backup can. A staging deploy
installs none of these units (`ai/staging.md`).

Nothing runs until a job's timer is enabled:

```bash
systemctl enable --now $APP_NAME-job@example.timer
systemctl list-timers "$APP_NAME-*"             # the next run of each timer
journalctl -u $APP_NAME-job@example.service     # what each run printed
systemctl disable --now $APP_NAME-job@example.timer
```

An enabled timer stays enabled across deploys, but a rebuilt server starts with none,
so a project that keeps a job adds its timer to the `systemctl enable --now` call in
`scripts/deploy.sh` and to the calls `scripts/tests/test-deploy.sh` expects. A job that
needs another schedule gets a timer of its own, `scripts/systemd/job@<name>.timer`: a
copy of `job@.timer` with its own `OnCalendar=`, added to the deploy's unit list and to
the units the test's `assert_units_installed` checks. systemd uses a unit file named for
an instance in place of the template.

### Why not Celery

Two derived apps adopted Celery with Redis for one daily job each, and neither job ran
reliably: neither worker imported the module that defines its task, and in one app beat
kept its schedule inside the container, so every deploy restarted the 24-hour countdown.
Nothing in either app enqueued work from a request. A timer needs no broker, worker, or
beat container, keeps its schedule across deploys, and reports a failure through
`scripts/alert.sh`, as the backups and the restore drill do. Celery and Redis come back
when requests enqueue work to run in the background, or when the work needs more than
one worker.

### Jobs without host access

A host that cannot run systemd timers, such as a container platform, runs a job in a
service of its own. `docker/job-loop.sh <job> <HH:MM>` sleeps until the next HH:MM UTC,
runs the job, retries a failed run every five minutes, and exits 1 after the third
failure in a row, so the restart policy and the platform's monitoring see it. It reads
the clock for every wait, so a restart keeps the schedule. The template starts no such
service. To add one, anchor the backend's `environment:` in
`docker/docker-compose.prod.yml` and add the service beside it:

```text
services:
  backend:
    environment: &backend-environment
      DATABASE_URL: ${DATABASE_URL}
      # ...the backend's other variables, unchanged
  job-example:
    build:
      context: .
      dockerfile: docker/backend.Dockerfile
    restart: unless-stopped
    entrypoint: ['/bin/sh', 'docker/job-loop.sh', 'example', '03:00']
    environment: *backend-environment
    depends_on:
      - backend
```

Run each job one way, through its timer or through a loop service, never both, or it
runs twice a day. A loop service has no `scripts/alert.sh`, so its exit is the only
signal; give it the uploads volume as well if the job touches stored files.

## Worktrees

When the clone is a bare-repo container (README, Worktrees), `main/` stays on `main`
and each issue gets a sibling worktree with its own `.env`, `COMPOSE_PROJECT_NAME`,
ports, `.venv`, and `node_modules`; `/plan-issue` and `/plan-pr` create it through
`scripts/worktree-setup.sh`, which forks a new branch from `origin/staging`. Run every
session inside a worktree, never in the container directory, which has no project
settings, hooks, or scripts. Never check an issue branch out in `main/`.
