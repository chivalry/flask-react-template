# Project Instructions

Replace this paragraph with the project's name and purpose when starting a project from
this template. The sections describe the layout, the commands, and the database rules
that every contributor and agent follows.

## Project Structure

- Backend: `src_back/` - Python/Flask
    - `api/` - Flask route handlers, one blueprint per domain
    - `models/` - SQLAlchemy models, one module per domain; `base.py` holds
      `BaseMixin`, `user.py` holds `Role` and `User`, and `__init__.py` re-exports every
      model, so `from src_back.models import User` works and every table registers
    - `schemas/` - Marshmallow schemas; `schemas/base.py` holds `BaseSchema` and
      `validate_ids_exist()`
    - `services/` - business logic by domain; `services/base.py` holds the generic
      `CRUDService`, `ChildRecordService`, and `require_unique_name()`,
      `services/errors.py` the exceptions services raise, and `services/users.py` the
      admin's account management
    - `tests/` - pytest; one `test_<module>.py` per module; `helpers.py` holds
      `persist()`
    - `app.py` - application factory, error handlers, SPA and upload serving
    - `auth.py` - `current_user` typed as `User`, for routes behind `@login_required`
    - `extensions.py` - shared Flask extensions and the declarative `Base`
    - `seed.py` - the seed every container start runs; it creates the first admin
    - `utils.py` - error envelopes, pagination in memory and in SQL, query-string
      parsing, quote folding, upload validation
- Frontend: `src_front/src/` - React/TypeScript with Vite
    - `api/` - axios client, the `resource()` factory, and typed API modules
    - `components/` - React components; `components/layout/AppShell.tsx` is the shell,
      `components/common/` holds the form and record-list kit, and
      `components/admin/` the admin screens
    - `hooks/` - shared hooks, including the TanStack Query hooks for each resource
    - `pages/` - top-level page components
    - `schemas/` - Zod form schemas, their defaults, and their payload mappers
    - `store/` - Zustand stores
    - `types/` - TypeScript types shared across modules
    - `utils/` - framework-free helpers, such as local-day dates
    - `test/` - Vitest tests mirroring `src/`; `test/utils/` holds the shared helpers
- `ai/` - these instructions; `AGENTS.md` and `.claude/CLAUDE.md` point here
- `docker/` - Dockerfiles, entrypoint, nginx config, production Compose override
- `migrations/` - Alembic migrations
- `plans/` - implementation plans; authoritative while a feature is in progress
- `scripts/` - local tooling (ports, worktrees) and server provisioning, deployment,
  TLS, and backup scripts
- `tools.md` - why each tool and library is in the repository

## Commands

All commands run from the repo root via npm scripts. Python tooling always goes through
`.venv/bin/`, installed from `requirements-dev.txt`; `requirements.txt` holds only the
runtime packages and is the file `docker/backend.Dockerfile` installs.

- `npm run test` - frontend and backend suites in parallel, both with coverage
- `npm run test:back` - `.venv/bin/python -m pytest` (100% coverage enforced)
- `npm run test:front` - `vitest run --coverage` (100% thresholds)
- `npm run lint` - ESLint; CI adds `--max-warnings=0`
- `npm run lint:py` - Ruff check and format check, pydoclint, function length,
  basedpyright
- `npm run lint:md` - markdownlint
- `npm run typecheck` - `tsc -b`
- `npm run format` and `npm run format:py` - Prettier and Ruff format
- `npm run fallow` - duplication and dead-code audit of the frontend
- `npm run docker:up` - start the dev stack, assigning free ports into `.env`
- `npm run docker:url` - wait for the dev frontend and print its URL
- `npm run docker:seed` - run the seed inside the backend container
- `npm run docker:down` - stop the dev stack
- `npm run deploy` - deploy production over SSH (`DEPLOY_HOST` or an argument)

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
  container. Seeds skip optional work themselves instead of failing. `scripts/deploy.sh`
  never runs `db upgrade` itself; it takes a database backup, restarts the stack, and
  waits for `/api/health`, which the backend serves only after the entrypoint finishes.
  This assumes one backend container; scaling it out means moving migrations into the
  deploy step.
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

`src_back/app.py` calls `load_dotenv()` at import, so `.env` values are visible to pytest
too. A test that depends on an environment variable sets or clears it with
`monkeypatch` first, as the `FLASK_ENV` and `CORS_ALLOWED_ORIGINS` tests in
`src_back/tests/test_app.py` do.

## Worktrees

When the clone is a bare-repo container (README, Worktrees), `main/` stays on `main`
and each issue gets a sibling worktree with its own `.env`, `COMPOSE_PROJECT_NAME`,
ports, `.venv`, and `node_modules`; `/plan-issue` and `/plan-pr` create it through
`scripts/worktree-setup.sh`. Run every session inside a worktree, never in the
container directory, which has no project settings, hooks, or scripts. Never check an
issue branch out in `main/`.
