# Flask React Template

A full-stack starting point: **Flask** (Python) backend and **React 19** (TypeScript +
Vite) frontend, with session authentication, image-upload scaffolding, 100% test
coverage on both sides, strict linting and typing, Docker for development and
production, and scripts to provision and deploy a single server.

## Stack

| Layer    | Technology                                                   |
| -------- | ------------------------------------------------------------ |
| Backend  | Flask, SQLAlchemy 2, Flask-Migrate, Flask-Login, marshmallow |
| Database | PostgreSQL 16                                                |
| Frontend | React 19, TypeScript 6, Vite, MUI, Axios, Zustand, Zod       |
| Tooling  | Ruff, basedpyright, pydoclint, pytest, ESLint, Prettier,     |
|          | Vitest, fallow, Husky, markdownlint                          |

## Quick start (local, no Docker)

```bash
git clone <your-repo-url> my-app
cd my-app

cp .env.example .env             # FLASK_ENV=development is already set

python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
docker compose up -d db          # or point DATABASE_URL at your own PostgreSQL
.venv/bin/flask --app src_back.app db upgrade
.venv/bin/flask --app src_back.app run

npm install                      # in a second terminal
npm run dev
```

Open <http://localhost:5174> (or whatever `FRONTEND_PORT` is set to in `.env`) and
register an account. Promote it to `admin` in the database when you need the
admin-only routes.

## Docker

```bash
npm run docker:up        # start; picks free ports and writes them to .env
npm run docker:url       # wait for the frontend and print its URL
npm run docker:up:build  # rebuild images first
npm run docker:down
```

The backend container runs migrations and the seed on every start; a seed that exits
non-zero stops the container. Uploaded files live in the `uploads_data` volume, so they
survive rebuilds.

## Worktrees

The repo works as a bare-repo container with one worktree per branch:

```bash
git clone --bare <your-repo-url> my-app && cd my-app
git config remote.origin.fetch '+refs/heads/*:refs/remotes/origin/*'  # bare clones skip it
git worktree add main
sh main/scripts/worktree-setup.sh feature/thing 1
```

`scripts/worktree-setup.sh` creates the worktree, copies `.env` from `main/`, gives the
stack its own `COMPOSE_PROJECT_NAME` and ports shifted by the offset, installs the venv
and `node_modules`, and points `core.hooksPath` at `.husky`, so several worktrees run
side by side.

## Scripts

| Command                   | Description                                     |
| ------------------------- | ----------------------------------------------- |
| `npm run dev`             | Vite dev server (no Docker)                     |
| `npm run build`           | Type check (`tsc -b`) and production build      |
| `npm run typecheck`       | `tsc -b` only                                   |
| `npm test`                | Frontend and backend suites, both with coverage |
| `npm run test:front`      | Vitest with 100% thresholds                     |
| `npm run test:back`       | pytest with 100% coverage enforced              |
| `npm run test:watch`      | Vitest in watch mode                            |
| `npm run lint`            | ESLint (CI adds `--max-warnings=0`)             |
| `npm run lint:py`         | Ruff, pydoclint, function length, basedpyright  |
| `npm run lint:md`         | markdownlint                                    |
| `npm run format`          | Prettier over the repository                    |
| `npm run format:py`       | Ruff format                                     |
| `npm run fallow`          | Duplication and dead-code audit                 |
| `npm run docker:up`       | Start containers (auto-assigns ports)           |
| `npm run docker:up:build` | Rebuild images then start containers            |
| `npm run docker:url`      | Print the running frontend's URL                |
| `npm run docker:seed`     | Run the seed inside the backend container       |
| `npm run docker:logs`     | Tail container logs                             |
| `npm run docker:down`     | Stop and remove containers                      |
| `npm run docker:prod:up`  | Start the production stack locally              |
| `npm run deploy`          | Deploy to `DEPLOY_HOST` (or a host argument)    |

## Project layout

```text
project/
├── ai/                # Project instructions for agents (see below)
├── src_back/          # Flask application
│   ├── app.py         # Application factory, error handlers, SPA and uploads
│   ├── extensions.py  # db (SQLAlchemy 2 Base), migrate, login_manager
│   ├── models.py      # BaseMixin, Role, User
│   ├── utils.py       # Error envelopes, pagination, parsing, upload checks
│   ├── api/           # Blueprints (health, auth)
│   ├── schemas/       # Marshmallow schemas; base.py has BaseSchema
│   ├── services/      # Business logic; base.py has the generic CRUD services
│   ├── seed.py        # Idempotent seed entry point
│   └── tests/         # pytest suite
├── src_front/         # React application
│   └── src/
│       ├── api/       # Axios client with interceptors; typed API modules
│       ├── components/  AppShell, ProtectedRoute, AuthFormLayout, ErrorBoundary
│       ├── hooks/     # useApiError, useAuthFormState
│       ├── pages/     # Home, Login, Register
│       ├── store/     # Zustand auth store
│       ├── types/     # AuthUser, PaginatedResponse
│       └── test/      # Vitest suite
├── migrations/        # Alembic migrations (initial schema included)
├── docker/            # Dockerfiles, entrypoint, nginx, production override
├── scripts/           # Ports, worktrees, provisioning, deploy, TLS, backups
├── plans/             # Implementation plans
└── .github/workflows/ # CI, issue auto-assign
```

## Editor testing and debugging

Install the recommended `vitest.explorer` extension for frontend test discovery and
debugging. Python tests use the Python extension's built-in pytest support and the
project venv. Editor pytest runs use `--no-cov` so a single test can run independently;
`npm test` still enforces full coverage for both suites.

The Run and Debug view includes Flask and the current Vitest test file. Start Vite
with `npm run dev` when debugging Flask alongside the frontend. Use the Testing view
to debug selected Python tests. Existing Jest and legacy Test Explorer extensions
can be disabled for this workspace if they create duplicate test entries.

The editor uses the workspace TypeScript 6 SDK. TypeScript 7 is deferred because
TypeScript ESLint currently requires TypeScript below 6.1. React Compiler optimizes
production builds; development and tests run authored source for readable debugging
and coverage.

Python 3.12 is the deployment and lint baseline, matching Docker and CI. A newer local
venv is supported, but does not permit syntax newer than the deployed runtime.

## Agent instructions

`ai/project.md`, `ai/conventions.md`, and `ai/domain.md` are the canonical project
instructions; `ai/backups.md` and `ai/tls.md` are the operations runbooks. `AGENTS.md`
and `.claude/CLAUDE.md` are thin adapters that point at them. `.claude/settings.json`
runs `tsc -b` after every TypeScript edit and assigns new GitHub issues to the
repository owner.

## Uploads

`validate_image_file()` in `src_back/utils.py` checks the extension and sniffs the MIME
type; stored files are served, login-protected, from `/uploads/<filename>`; bodies over
25 MB get a JSON 413. Set `UPLOAD_FOLDER` in `.env`; under Docker the `uploads_data`
volume persists files across rebuilds.

To remove a stored file, a service overrides `after_delete` and calls `delete_upload()`,
also in `src_back/utils.py`, so the file goes only once the row's deletion is committed.
A file that is already gone is ignored.

## Deployment

The production stack runs on one Ubuntu host behind host nginx with Let's Encrypt.
Database and backend ports are bound to loopback; only nginx faces the network.

On the server:

```bash
git clone <your-repo-url> ~/my-app && cd ~/my-app
bash scripts/provision.sh example.com                # packages, Docker, nginx, .env
bash scripts/certbot-setup.sh --email you@example.com  # first certificate, after DNS
```

`provision.sh` writes `.env` with generated secrets; review it before deploying.

Then, from your machine, `DEPLOY_HOST=root@example.com npm run deploy`.
`scripts/deploy.sh` backs up the database before migrating, rebuilds the containers,
installs the nginx site, and enables certificate monitoring. Once the `SPACES_*`
variables are filled in, `bash scripts/install-backup.sh` enables nightly off-site
backups with alerts on failure. `ai/backups.md` and `ai/tls.md` cover restores,
alerts, and renewals.
