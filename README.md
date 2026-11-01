# Flask React Template

A full-stack starting point: **Flask** (Python) backend and **React 19** (TypeScript +
Vite) frontend, with session authentication, image-upload scaffolding, 100% test
coverage on both sides, strict linting and typing, Docker for development and
production, and scripts to provision and deploy a single server, with an optional
staging stack beside production.

## Stack

| Layer    | Technology                                                   |
| -------- | ------------------------------------------------------------ |
| Backend  | Flask, SQLAlchemy 2, Flask-Migrate, Flask-Login, marshmallow |
| Database | PostgreSQL 16                                                |
| Frontend | React 19, TypeScript 6, Vite, MUI, Axios, TanStack Query,    |
|          | Zustand, Zod                                                 |
| Tooling  | Ruff, basedpyright, pydoclint, pytest, ESLint, Prettier,     |
|          | Vitest, fallow, Husky, markdownlint                          |

[`tools.md`](tools.md) says why each tool and library in the repository is here.

## Starting a new project

After creating a repository from this template, replace the template's name and
placeholders:

- `name` in `package.json`, the two matching `name` fields at the top of
  `package-lock.json`, and `name` in `.devcontainer/devcontainer.json`
- `COMPOSE_PROJECT_NAME` and `APP_NAME` in `.env.example`, and in `.env` if it already
  exists
- `APP_NAME`, `COMPOSE_PROJECT_NAME`, `PRODUCTION_DIR`, `STAGING_HTPASSWD`, and
  `WEBAUTHN_RP_NAME` in `.env.staging.example`, which carry the template's name
- the fallback project name on the first line of `docker-compose.yml`
- `Flask React Template`, the last fallback for `WEBAUTHN_RP_NAME` in `src_back/app.py`,
  and the test that expects it in `src_back/tests/test_app.py`
- the `<title>` in `src_front/index.html`
- `APP_TITLE` in `src_front/src/appTitle.ts`, which the app bar and the tab title use,
  and the tests that expect it, `src_front/src/test/App.test.tsx` and
  `src_front/src/test/components/layout/AppShell.test.tsx`
- this README's title and the `my-app` placeholders in its commands
- the placeholder paragraphs at the top of `ai/project.md` and `ai/domain.md`

GitHub copies only the default branch, `staging`, to a repository created from the
template, unless "Include all branches" is ticked. Create `main` from it
(`git push origin origin/staging:refs/heads/main`), keep `staging` as the default
branch, and see `ai/staging.md`.

`plans/archive/` holds the template's own finished plans. Delete them if the new project
should start without that history; `plans/archive/.gitkeep` keeps the folder.

## Quick start (local, no Docker)

```bash
git clone <your-repo-url> my-app
cd my-app

cp .env.example .env             # FLASK_ENV=development is already set
                                 # set ADMIN_EMAIL and ADMIN_PASSWORD in .env

python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
docker compose up -d db          # or point DATABASE_URL at your own PostgreSQL
.venv/bin/flask --app src_back.app db upgrade
.venv/bin/python -m src_back.seed   # creates the admin from ADMIN_EMAIL/ADMIN_PASSWORD
.venv/bin/flask --app src_back.app run

npm install                      # in a second terminal
npm run dev
```

Open <http://localhost:5174> (or whatever `FRONTEND_PORT` is set to in `.env`) and
sign in as the admin from `.env`. Registration stays open and always creates a plain
user; the admin changes roles, passwords, and active status on the Users tab of the
Admin page.

## Docker

```bash
npm run docker:up        # build, start, and watch; picks free ports for .env
npm run docker:url       # wait for the frontend and print its URL
npm run docker:down
```

`npm run docker:up` builds both images from the working tree, starts the stack, and
stays attached while Compose watches the source, so a saved edit reaches the running
containers with no rebuild or restart command:

- Saving, adding, or deleting a file under `src_back/` or `migrations/` reaches the
  backend, and Flask's development server reloads; debug mode and its debugger stay
  off. An edit that breaks an import leaves the backend answering 500 until the fix
  lands, even when the fix is a new module, and a backend started while an import is
  broken restarts until the fix is saved.
- A file saved under `src_front/` reaches the open page through Vite's hot module
  replacement.
- A deleted or renamed file leaves the container as well.
- A change to `docker/entrypoint.sh`, `vite.config.ts`, or a `tsconfig*.json` restarts
  its container, and a change to `requirements.txt`, `package.json`,
  `package-lock.json`, or a Dockerfile rebuilds its image and replaces the container.

Building on every start reuses the cached dependency layers, so it costs little unless a
dependency file changed, and it brings in whatever changed while the stack was stopped,
so no separate rebuild command is needed. A change to a Compose file takes effect at the
next `npm run docker:up`.

`npm run docker:up -- -d` starts in the background without watching and says so;
`docker compose watch --no-up` watches a stack started that way. The watch rules live in
`docker-compose.override.yml`, which Compose reads only when no `-f` is given, so the
production stack never loads them. Watching needs Docker Compose 2.24.7 or newer.

A revision generated with `db migrate` reaches the backend without restarting its
container, so the entrypoint's `db upgrade` does not run and the revision waits for
review; apply it from the host with `db upgrade` as before. Every backend start runs
that `db upgrade`, so review a new revision before anything restarts or rebuilds the
backend: `npm run docker:up`, `docker compose restart`, or a saved change to
`docker/entrypoint.sh`, `requirements.txt`, or `docker/backend.Dockerfile`. A database
at a revision the checkout lacks, such as one applied on another branch, stops the
backend at its next start: check out a branch that has the revision and run
`db downgrade` to one both branches share.

The backend container runs migrations and the seed on every start; a seed that exits
non-zero stops the container. With `ADMIN_EMAIL` and `ADMIN_PASSWORD` in `.env`, the
first start creates that admin. Uploaded files live in the `uploads_data` volume, so they
survive rebuilds.

The backend image installs only `requirements.txt`, the runtime packages, plus
`watchdog` for the reloader when the dev stack builds it. The lint, type-check, and test
tools come from `requirements-dev.txt` and run from `.venv`, never inside the Compose
containers.

The backend runs as the unprivileged `app` user (uid 10001), never as root. Its source
belongs to root in production, so the running app cannot change it; the dev image
gives it to `app`, because file watch writes the synced files as that user.

## Worktrees

To work on several branches at once, keep the clone as a bare-repo container with one
worktree per branch. The bare repository lives in `.git`, and `main/` holds `main`:

```bash
mkdir my-app && cd my-app
git clone --bare <your-repo-url> .git
git config remote.origin.fetch '+refs/heads/*:refs/remotes/origin/*'  # bare clones skip it
git fetch origin
git worktree add main main
```

An existing clone converts in place and keeps its tags and local branches: move
everything except `.git` out of it, run `git config core.bare true` and
`git worktree add main main` there, then move `.env` into `main/` and rebuild `.venv`
(a virtualenv embeds its own path) and `node_modules` in it.

Each further branch gets its own worktree, created from the container directory:

```bash
sh main/scripts/worktree-setup.sh issue-12-some-slug
```

`scripts/worktree-setup.sh` creates the worktree on a new branch from `origin/staging`
(or `origin/main` where there is no `staging`), copies `.env` from `main/`, gives the
stack its own `COMPOSE_PROJECT_NAME`, and shifts its ports by the smallest offset that
no other worktree's `.env` reserves and nothing is listening on; a second argument sets
the offset instead. It then builds the venv, checks that it imports the project, and
installs `node_modules`, and `npm install` points the shared `core.hooksPath` at
`.husky/_`, which resolves inside each worktree.

The first `python3` on `PATH` outside a virtualenv builds the venv. `PYTHON_BIN`, a
command or a path, names another, and the script refuses it if it sits inside a
virtualenv: a venv built from another venv can record a versioned Homebrew Cellar
directory as its base, which the next `brew upgrade` deletes. The script warns if the
new venv recorded one anyway.

Open each worktree in its own VS Code window, never the container directory: only a
worktree has the `.vscode/settings.json` that points the Python extension at its
`.venv`. The script opens the new worktree that way when `code` is on `PATH`, unless
`--no-open` comes before the branch name.

`npm run doctor`, run in a worktree, reports whether it still works. It exits 1 when
`.venv/bin/python` does not run or the project does not import, and it warns about a
venv based on a Cellar path, a missing `.vscode/settings.json`, and missing
`node_modules`.

Once a branch has merged, remove its stack, volumes, images, worktree, and local branch
from the container directory:

```bash
(cd issue-12-some-slug && npm run docker:down -- -v --rmi local)
git worktree remove issue-12-some-slug
git branch -D issue-12-some-slug
```

## Scripts

| Command                  | Description                                     |
| ------------------------ | ----------------------------------------------- |
| `npm run dev`            | Vite dev server (no Docker)                     |
| `npm run build`          | Type check (`tsc -b`) and production build      |
| `npm run typecheck`      | `tsc -b` only                                   |
| `npm test`               | Frontend and backend suites, both with coverage |
| `npm run test:front`     | Vitest with 100% thresholds                     |
| `npm run test:back`      | pytest with 100% coverage enforced              |
| `npm run test:scripts`   | Shell script syntax checks and `scripts/tests/` |
| `npm run test:watch`     | Vitest in watch mode                            |
| `npm run lint`           | ESLint (CI adds `--max-warnings=0`)             |
| `npm run lint:py`        | Ruff, pydoclint, function length, basedpyright  |
| `npm run lint:md`        | markdownlint                                    |
| `npm run format`         | Prettier over the repository                    |
| `npm run format:py`      | Ruff format                                     |
| `npm run fallow`         | Duplication and dead-code audit                 |
| `npm run doctor`         | Check this worktree's venv and `node_modules`   |
| `npm run docker:up`      | Build, start, and watch the dev stack           |
| `npm run docker:url`     | Print the running frontend's URL                |
| `npm run docker:seed`    | Run the seed inside the backend container       |
| `npm run docker:logs`    | Tail container logs                             |
| `npm run docker:down`    | Stop and remove containers                      |
| `npm run docker:prod:up` | Start the production stack locally              |
| `npm run deploy`         | Deploy to `DEPLOY_HOST` (or a host argument)    |
| `npm run deploy:staging` | Deploy the staging clone (`ai/staging.md`)      |

## Project layout

```text
project/
├── ai/                # Project instructions for agents (see below)
├── src_back/          # Flask application
│   ├── app.py         # Application factory, error handlers, SPA and uploads
│   ├── auth.py        # current_user typed as User
│   ├── extensions.py  # db (SQLAlchemy 2 Base), migrate, login_manager
│   ├── jobs/          # Scheduled jobs; example.py is the one to copy
│   ├── mailer.py      # Plain-text SMTP mail; off while SMTP_HOST is blank
│   ├── models/        # Package: base.py has BaseMixin, user.py has Role and User
│   ├── utils.py       # Error envelopes, pagination, parsing, upload checks, CSV
│   ├── api/           # Blueprints (health, auth, users, audit logs)
│   ├── schemas/       # Marshmallow schemas; base.py has BaseSchema
│   ├── services/      # Business logic; base.py has the generic CRUD services
│   ├── seed.py        # Idempotent seed; creates the first admin
│   └── tests/         # pytest suite
├── src_front/         # React application
│   └── src/
│       ├── api/       # Axios client, resource(), downloadFile(), typed API modules
│       ├── components/  Shell, route guards, error boundaries, layout/, common/, admin/
│       ├── hooks/     # TanStack Query hooks per resource, shared hooks
│       ├── pages/     # Home, Login, Register, Admin
│       ├── schemas/   # Zod form schemas and payload mappers
│       ├── store/     # Zustand auth store
│       ├── types/     # AuthUser, User, PaginatedResponse
│       ├── utils/     # Local-day dates, record counts, account labels
│       └── test/      # Vitest suite mirroring src/; utils/ has shared helpers
├── migrations/        # Alembic migrations (initial schema included)
├── docker/            # Dockerfiles, entrypoint, job loop, nginx, production override
├── scripts/           # Ports, worktrees, provisioning, deploy, TLS, backups
│   └── tests/         # Shell script tests (npm run test:scripts)
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
instructions; `ai/auth.md`, `ai/backups.md`, `ai/tls.md`, and `ai/staging.md` are the
operations runbooks. `AGENTS.md` and `.claude/CLAUDE.md` are thin adapters that point at
them. `.claude/settings.json` runs `tsc -b` after every TypeScript edit and assigns new
GitHub issues to the repository owner.

## Uploads

`validate_image_file()` in `src_back/utils.py` checks the extension and sniffs the MIME
type; stored files are served, login-protected, from `/uploads/<filename>`; bodies over
25 MB get a JSON 413. Set `UPLOAD_FOLDER` in `.env`; under Docker the `uploads_data`
volume persists files across rebuilds.

To remove a stored file, a service overrides `after_delete` and calls `delete_upload()`,
also in `src_back/utils.py`, so the file goes only once the row's deletion is committed.
A file that is already gone is ignored.

The `app` user owns `src_back/uploads` in the backend image, and Docker gives a new,
empty `uploads_data` volume that owner. Docker never re-owns a volume that already holds
files, so one written while the backend ran as root keeps root as its owner, and saving
an upload then fails with a 500. `scripts/deploy.sh` hands the volume to the app user on
every redeploy; in development, hand it over once yourself, naming the volume after
`COMPOSE_PROJECT_NAME`:

```bash
docker run --rm -v <COMPOSE_PROJECT_NAME>_uploads_data:/uploads alpine \
  chown -R 10001:10001 /uploads
```

## Branches and releases

`staging` is the default branch: feature branches fork from it and their PRs merge into
it. A release is a PR from `staging` into `main`, merged with a merge commit, and
production then deploys `main`. `ai/conventions.md` holds the rules, and
`ai/staging.md` the commands and the staging server.

## Deployment

The production stack runs on one Ubuntu host behind host nginx with Let's Encrypt.
Database and backend ports are bound to loopback; only nginx faces the network. Host
nginx also sends the security headers and throttles sign-in attempts; `ai/tls.md` and
`ai/auth.md` describe both.

On the server:

```bash
git clone --branch main <your-repo-url> ~/my-app && cd ~/my-app
bash scripts/provision.sh example.com                # packages, Docker, nginx, .env
bash scripts/certbot-setup.sh --email you@example.com  # first certificate, after DNS
```

`provision.sh` writes `.env` with generated secrets; review it before deploying.

Then, from your machine, `DEPLOY_HOST=root@example.com npm run deploy`;
`npm run deploy:staging` deploys the staging clone the same way. `scripts/deploy.sh`
first refuses a clone on the wrong branch or in the wrong environment: production
deploys `main`, and a plain clone checks out `staging`, the default branch. It then
backs up the database before migrating, hands the uploads volume to the backend's
unprivileged user, rebuilds the containers, installs the nginx site, and enables
certificate monitoring, nightly backups kept on the server, and a weekly drill that
restores the newest one. It also installs the scheduled-job units, which run a job from
`src_back/jobs/` once its timer is enabled (`ai/project.md`). A staging deploy skips the
backup, the renewal hook, and the timers. Once the `SPACES_*` variables are filled in,
`bash scripts/install-backup.sh` adds off-site copies in a bucket. Failures alert
through `ALERT_WEBHOOK_URL`; `ai/backups.md` and `ai/tls.md` cover restores, alerts,
and renewals. `ai/staging.md` covers running staging beside production.
