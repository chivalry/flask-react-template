# Issue #13: Update the Docker dev containers as source files change

## Context

Both Dockerfiles copy the source into the images, `docker-compose.yml` bind-mounts none
of it, and `docker/entrypoint.sh` starts gunicorn without a reloader, so every edit
needs `npm run docker:up:build`. This ports hukilau's Compose file watch (hukilau#10,
commits `bb226be` and `db0bbb9`) to a template that has no LAN stack and that already
has #15's shell tests (PR #45, merged), which pin today's behaviour; this change extends
those tests rather than creating them, and also brings `tools.md` up to date. No backend
endpoint, API client, or frontend source changes.

## Decisions

These come from the issue and from hukilau's review of `bb226be`; do not revisit them.

- **Watch by default.** `npm run docker:up` runs `docker compose up --build --watch`.
  Compose refuses `--watch` with `--detach` or `--wait`, so a detached start builds,
  starts, and says it is not watching, naming `docker compose watch --no-up`.
- **Build on every start.** Containers never run an image older than the working tree,
  and cached layers keep the build to seconds, so `docker:up:build` is removed.
- **Flask's development server, not gunicorn `--reload`.** Its reloader keeps serving
  through an edit that breaks an import (500 per request) and recovers when the fix
  lands. Debug mode and the debugger stay off because `docker-compose.yml:27` publishes
  the backend port on every interface.
- **watchdog through a build argument.** Without it Werkzeug falls back to its stat
  reloader, which misses added and deleted modules. Only the dev override sets
  `DEVELOPMENT_PACKAGES`, so production images install nothing more.
- **`migrations/` syncs without a restart.** A container restart runs the entrypoint's
  `db upgrade`, which would apply a generated revision before review. (Flask's reloader
  still reloads its process when the file appears; that runs no migration.)
- **The rules live in `docker-compose.override.yml`**, which Compose loads only when no
  `-f` is given. Every production invocation passes `-f`: `scripts/deploy.sh:49-51`,
  `scripts/backup.sh:31-33`, the runbooks in `ai/`, and the `docker:prod:*` npm scripts
  (`package.json:31-32`).
- **`src_back/uploads` joins `.dockerignore`.** Compose applies the build context's
  `.dockerignore` to watched paths, so host uploads stay out of the watch, and out of
  the images, which would otherwise seed a newly created `uploads_data` volume.
- **The Compose floor for the dev stack is 2.24.7**, not the issue's 2.22. Compose's
  release notes: `docker compose watch` went GA in 2.22.0, `sync+restart` arrived in
  2.23.0, `up --watch` in 2.24.7 (#11525), and 2.27.2 made `up` reject `--detach` with
  `--watch` and stopped `up --watch` from blocking shutdown. Production keeps its 2.24.4
  floor, since it never reads the override.

## Branch

`issue-13-update-the-docker-dev-containers-as` — already checked out; PR #46 exists.

## Change

**12 files**: new `docker-compose.override.yml`; edited `docker/backend.Dockerfile`,
`docker/entrypoint.sh`, `scripts/up.sh`, `.dockerignore`, `package.json`,
`scripts/tests/test-compose-config.sh`, `scripts/tests/test-entrypoint.sh`,
`scripts/tests/test-up.sh`, `README.md`, `ai/project.md`, `tools.md`.

Line numbers are those of `origin/main` (`154bd39`), before any edit. Every line written
stays within 90 characters.

### docker-compose.override.yml — new: watch rules and the watchdog build argument

hukilau's file, with its LAN wording dropped and the Compose floor added. All four
`tsconfig*.json` files exist here.

```yaml
# Development only. Compose merges this file onto docker-compose.yml whenever no -f is
# given, as in scripts/up.sh and the docker:* npm scripts other than docker:prod:*. The
# production stack always passes -f, so it never loads it.
#
# `docker compose up --watch` (scripts/up.sh's default, which needs Compose 2.24.7 or
# newer) applies these rules: sync copies saved and deleted files into the running
# container, sync+restart also restarts it, and rebuild builds the image and replaces
# the container. The build context's .dockerignore applies too, so caches, coverage
# reports, and local uploads stay out.
services:
  backend:
    build:
      args:
        # Flask's reloader switches to watchdog once it is installed, so modules being
        # added and deleted reload the backend too. See docker/backend.Dockerfile.
        DEVELOPMENT_PACKAGES: watchdog==6.0.0
    develop:
      watch:
        # Flask's reloader, started by docker/entrypoint.sh, picks these up.
        - action: sync
          path: ./src_back
          target: /app/src_back
        # No restart: a restart runs db upgrade, and a new revision waits for review.
        - action: sync
          path: ./migrations
          target: /app/migrations
        - action: sync+restart
          path: ./docker/entrypoint.sh
          target: /app/docker/entrypoint.sh
        - action: rebuild
          path: ./requirements.txt
        - action: rebuild
          path: ./docker/backend.Dockerfile

  frontend:
    develop:
      watch:
        # Vite's dev server picks these up and updates the page through HMR.
        - action: sync
          path: ./src_front
          target: /app/src_front
        - action: sync+restart
          path: ./vite.config.ts
          target: /app/vite.config.ts
        - action: sync+restart
          path: ./tsconfig.json
          target: /app/tsconfig.json
        - action: sync+restart
          path: ./tsconfig.app.json
          target: /app/tsconfig.app.json
        - action: sync+restart
          path: ./tsconfig.node.json
          target: /app/tsconfig.node.json
        - action: sync+restart
          path: ./tsconfig.test.json
          target: /app/tsconfig.test.json
        - action: rebuild
          path: ./package.json
        - action: rebuild
          path: ./package-lock.json
        - action: rebuild
          path: ./docker/frontend.Dockerfile
```

### docker/backend.Dockerfile — `DEVELOPMENT_PACKAGES` build argument

Insert between line 6 (`RUN pip install ... requirements.txt`) and line 8
(`COPY src_back/ ./src_back/`), so the layer sits after the requirements and stays
cached across source edits. `$DEVELOPMENT_PACKAGES` is unquoted on purpose, so it can
name several packages.

```dockerfile
# The dev stack sets this to watchdog (docker-compose.override.yml): Flask's reloader uses
# it when installed and then sees modules being added and deleted, which its fallback stat
# reloader misses. Production builds leave it empty and install nothing more.
ARG DEVELOPMENT_PACKAGES=
RUN if [ -n "$DEVELOPMENT_PACKAGES" ]; then \
      pip install --no-cache-dir $DEVELOPMENT_PACKAGES; \
    fi

```

The unused `CMD` on line 14 stays: the Compose `entrypoint` ignores it.

### docker/entrypoint.sh — Flask's reloader in development

Insert before line 12 (`echo "Starting gunicorn..."`); lines 12-17 stay as they are.

```sh
# The dev stack (FLASK_ENV=development in docker-compose.yml) runs Flask's development
# server. Its reloader applies the edits Compose syncs in, including added and deleted
# modules, since the dev build installs watchdog for it, and keeps serving through an
# edit that breaks an import. Debug mode and its debugger stay off because the backend
# port is published on every interface. Every other stack runs gunicorn.
if [ "${FLASK_ENV:-}" = development ]; then
  echo "Starting the Flask development server..."
  exec flask --app src_back.app run --host 0.0.0.0 --port 5000 --reload --no-debugger
fi

```

### scripts/up.sh — build and watch in development

Replace line 2 with:

```sh
# Start containers. In development, auto-assigns free host ports, then builds the images
# from the working tree and watches it (develop.watch in docker-compose.override.yml),
# so saved edits reach the running containers.
```

Replace line 69 (`docker compose up "$@"`) with the block below. The detection matches
`-d`, `--detach`, and `--wait` exactly; rarer spellings such as `--detach=true` or
`-dV` fall through to `--watch`, which Compose 2.27.2 and later reject with an error
rather than misbehaving, so they need no handling.

```sh
# Production starts as it always has: no build, no watch.
if [ "$flask_env" = "production" ]; then
  docker compose up "$@"
  exit
fi

# Compose cannot watch a detached stack, and --wait implies detached, so say so.
detached=
for arg in "$@"; do
  case "$arg" in
    -d | --detach | --wait) detached=1 ;;
  esac
done

if [ -n "$detached" ]; then
  echo "Starting detached, so not watching: saved edits will not reach the containers."
  echo "  Watch them with: docker compose watch --no-up"
  docker compose up --build "$@"
else
  docker compose up --build --watch "$@"
fi
```

### .dockerignore — keep local uploads out

Append after line 14 (`plans`):

```text
# Local-run uploads stay out of the images, so out of a newly created uploads_data
# volume, and out of the dev stack's file watch.
src_back/uploads
```

### package.json — retire `docker:up:build`

Delete line 25 (`"docker:up:build": "sh scripts/up.sh --build",`). The `docker:build`
script on line 27 stays; without `-f` it now builds the dev backend with watchdog, which
is what a dev build should be.

### scripts/tests/test-compose-config.sh — watch only in development

Replace the header comment, lines 2-7:

```bash
# Render the development and production Compose configurations and check that only the
# development stack carries file watch and watchdog, that every watched path exists and
# migrations sync without restarting the backend, and what the production stack must
# keep: loopback-only ports and no database port; a backend that runs
# docker/entrypoint.sh under FLASK_ENV=production, where it starts gunicorn, with
# GUNICORN_WORKERS and secure session cookies; and the nginx frontend. It needs the
# docker CLI with Compose, and jq, but no daemon; without them it exits 77, which
# scripts/tests/run-all.sh counts as a skip outside CI. It runs under macOS's bash 3.2
# and on Linux.
```

After line 48 (the dev frontend check), add the dev checks. The migrations check and the
path loop go beyond hukilau: the first pins the decision that a revision never restarts
the backend, and the second catches a watch rule left pointing at a renamed file, which
would silently watch nothing. Rendered watch paths are absolute.

```bash
check dev '.services.backend.develop.watch | length > 0' 'backend file watch'
check dev '.services.frontend.develop.watch | length > 0' 'frontend file watch'
check dev '.services.backend.build.args.DEVELOPMENT_PACKAGES | test("^watchdog==")' \
  'watchdog in the backend build'
# A restart runs the entrypoint's db upgrade, which would apply an unreviewed revision.
check dev '[.services.backend.develop.watch[] | select(.target == "/app/migrations")
  | .action] == ["sync"]' 'migrations synced without a restart'
# A watch path that does not exist, such as a renamed tsconfig file, watches nothing.
jq -r '.services[].develop.watch[]?.path' "$TEST_DIR/dev.json" > "$TEST_DIR/watch-paths"
while IFS= read -r path; do
  [ -e "$path" ] || { echo "The dev watch path $path does not exist." >&2; exit 1; }
done < "$TEST_DIR/watch-paths"
```

After line 56 (the prod `FLASK_ENV` check), add:

```bash
# Under FLASK_ENV=production the entrypoint starts gunicorn (test-entrypoint.sh).
check prod '.services.backend.entrypoint == ["/bin/sh", "docker/entrypoint.sh"]' \
  'docker/entrypoint.sh as the backend entrypoint'
check prod '[.services[] | has("develop")] | any | not' 'no file watch'
check prod '(.services.backend.build.args.DEVELOPMENT_PACKAGES // "") == ""' \
  'no development packages in the backend build'
check prod '[.. | strings | select(test("--reload|flask run"))] | length == 0' \
  'no reload flag or development server command'
```

### scripts/tests/test-entrypoint.sh — the development branch

No existing assertion breaks, but nothing tests the new branch and two comments go
stale. `run_entrypoint` keeps its `[NAME=value...]` signature (lines 36-42).

Header, lines 2-4:

```bash
# Exercise docker/entrypoint.sh's development and production paths with stub flask,
# python, and gunicorn commands. It runs under macOS's bash 3.2 and on Linux in CI, so
# it avoids bash 4 features; CI's sh is dash, as the backend image's is.
```

After line 34:

```bash
FLASK_SERVER='flask --app src_back.app run --host 0.0.0.0 --port 5000'
FLASK_SERVER="$FLASK_SERVER --reload --no-debugger"
```

Lines 49-50: the development case goes first, and the comment above the gunicorn cases
becomes the second one here:

```bash
# Development migrates, seeds, and then runs Flask's reloader with the debugger off.
run_entrypoint FLASK_ENV=development
expect_calls "$MIGRATE" "$SEED" "$FLASK_SERVER"

# Every other stack, including one that never sets FLASK_ENV, migrates, seeds, and then
# runs gunicorn, with two workers unless GUNICORN_WORKERS, which the production override
# sets, says otherwise.
```

Lines 58-73 become the block below, so a failed migration or seed is checked in both
branches:

```bash
# A failed migration or seed stops the container before either server starts.
touch "$TEST_DIR/fail-flask"
for flask_env in development production; do
  if run_entrypoint "FLASK_ENV=$flask_env"; then
    echo "Expected a failed migration to stop the $flask_env entrypoint." >&2
    exit 1
  fi
  expect_calls "$MIGRATE"
done
rm "$TEST_DIR/fail-flask"

touch "$TEST_DIR/fail-python"
for flask_env in development production; do
  if run_entrypoint "FLASK_ENV=$flask_env"; then
    echo "Expected a failed seed to stop the $flask_env entrypoint." >&2
    exit 1
  fi
  expect_calls "$MIGRATE" "$SEED"
done
rm "$TEST_DIR/fail-python"
```

### scripts/tests/test-up.sh — watched and detached starts

Every development start now carries `--build`, and an attached one `--watch`, so the
assertions on lines 79, 123, and 136 break; production gains refutations and an
attached case.

Header, lines 2-4:

```bash
# Exercise scripts/up.sh's port assignment, its watched and detached starts, its
# already-running path, and its production path with stub docker and lsof commands. It
# runs under macOS's bash 3.2 and on Linux in CI, so it avoids bash 4 features.
```

First start: the comment on lines 67-68 gains the sentence `It then builds and
watches.` (re-wrapped to 90). Line 79 becomes the first line below, and the second is
new:

```bash
assert_contains '^docker compose up --build --watch$' "$COMMANDS"
refute_contains 'not watching' "$OUTPUT"
```

Shifted ports: the comment on lines 112-113 ends `... and up.sh hands its arguments to
docker compose up after its own flags.` Line 123 becomes the first line below, and the
new cases follow it, before the running-stack case:

```bash
assert_contains '^docker compose up --build -d backend$' "$COMMANDS"

# A watched start passes its arguments after the development flags too.
run_up backend
assert_contains '^docker compose up --build --watch backend$' "$COMMANDS"
refute_contains 'not watching' "$OUTPUT"

# A detached start builds, cannot watch, says so, and names the command that watches.
for flag in -d --detach --wait; do
  run_up "$flag"
  assert_contains "^docker compose up --build $flag\$" "$COMMANDS"
  refute_contains '--watch' "$COMMANDS"
  assert_contains 'not watching' "$OUTPUT"
  assert_contains 'docker compose watch --no-up' "$OUTPUT"
done
```

Running stack: the comment on lines 125-126 becomes `A running stack keeps the ports in
.env, even one that now looks busy, and is still built and watched.` Line 136 becomes:

```bash
assert_contains '^docker compose up --build --watch$' "$COMMANDS"
```

Production: the comment on line 139 becomes `Production assigns no ports, even with one
busy, and starts as asked, attached or detached, with neither a build nor a watch.`
After line 147 add:

```bash
refute_contains '--build|--watch' "$COMMANDS"
refute_contains 'not watching' "$OUTPUT"
run_up
assert_contains '^docker compose up$' "$COMMANDS"
refute_contains '--build|--watch' "$COMMANDS"
```

### README.md — the Docker section and the Scripts table

Replace lines 70-75 (the code block) with the block below, followed by the new prose.
Lines 77-80 (migrations, seed, admin, `uploads_data`) stay as they are.

````markdown
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
````

Lines 82-84 become:

```markdown
The backend image installs only `requirements.txt`, the runtime packages, plus
`watchdog` for the reloader when the dev stack builds it. The lint, type-check, and test
tools come from `requirements-dev.txt` and run from `.venv`, never inside the Compose
containers.
```

Scripts table: line 147's description becomes `Build, start, and watch the dev stack`,
and line 148 (`docker:up:build`) is deleted. The first column then narrows by one
character, so run `npx prettier --write README.md` to re-pad the table (CI runs
`npx prettier --check .`), and confirm with `git diff README.md` that nothing else moved.

### ai/project.md — Commands and the entrypoint bullet

Lines 51-53 become:

```markdown
All commands run from the repo root via npm scripts. Python tooling always goes through
`.venv/bin/`, installed from `requirements-dev.txt`; `requirements.txt` holds only the
runtime packages and is the file `docker/backend.Dockerfile` installs, adding `watchdog`
for the reloader only when the dev stack builds it.
```

Line 67 becomes the bullet below. The sentence about running it in the background is
for agents, whose foreground commands would block on an attached stack.

```markdown
- `npm run docker:up` - build and start the dev stack, assigning free ports into `.env`,
  then watch it (`develop.watch` in `docker-compose.override.yml`) so saved edits reach
  the running containers. It stays attached, so an agent runs it as a background
  command; `npm run docker:up -- -d` starts detached and does not watch
```

Lines 90-96 become:

```markdown
- `docker/entrypoint.sh` owns migrations: it runs `db upgrade` and the seed on every
  container start, in development and in production, and a non-zero exit stops the
  container. Seeds skip optional work themselves instead of failing. It then starts
  gunicorn, or, under `FLASK_ENV=development`, Flask's development server with the
  reloader and without the debugger; the dev build installs `watchdog`, so the reloader
  also sees added and deleted modules. The dev stack syncs `migrations/` into the
  backend without restarting its container, so a generated revision is applied by
  `db upgrade` or at the next backend start, never by the sync. `scripts/deploy.sh`
  never runs `db upgrade` itself; it takes a database backup, restarts the stack, and
  waits for `/api/health`, which the backend serves only after the entrypoint
  finishes. This assumes one backend container; scaling it out means moving
  migrations into the deploy step.
```

### tools.md — versions, gunicorn, watchdog, Docker, and the backend image

Seven passages become false or incomplete; #12 left out the watchdog and override
entries only because the template lacked them. Prettier preserves prose wrapping, so
re-wrapped paragraphs stay as written.

Lines 3-8, the introduction:

```markdown
Why each tool and library in this repository is here, one short entry apiece. The
pinned versions live in `requirements.txt`, `requirements-dev.txt`, and `package.json`,
apart from watchdog's in `docker-compose.override.yml`; the server-side tools are
installed by the scripts under `scripts/` and the images under `docker/`.
`ai/project.md` describes the repository's own scripts and commands, and the runbooks
`ai/backups.md` and `ai/tls.md` describe how the operations tools are used. This file
only explains what each one is for.
```

Line 34, the backend runtime section's introduction:

```markdown
Installed from `requirements.txt` into the backend image and into `.venv`, except
watchdog, which only the dev stack's backend image gets.
```

Lines 38-39, the end of the Flask entry: `Its \`flask\` command applies the migrations
and runs the development server, on the host and in the dev stack.`

Lines 78-80 (gunicorn), with the new watchdog entry after them:

```markdown
- **gunicorn**: the production WSGI server. `docker/entrypoint.sh` starts it after the
  migrations and the seed whenever `FLASK_ENV` is not `development`, with
  `GUNICORN_WORKERS` workers: 2 by default, 4 in the production override. The dev stack
  and work without Docker use Flask's development server.
- **watchdog**: not in `requirements.txt`; the dev stack's build installs it into the
  backend image through the `DEVELOPMENT_PACKAGES` build argument. Flask's reloader uses
  it when present and then notices modules being added and deleted, which its fallback
  stat reloader misses.
```

Lines 219-222 (Docker Engine):

```markdown
- **Docker Engine**: runs the database, backend, and frontend as containers in
  development and on the production server, so the backend builds from the same
  Dockerfile and runs the same entrypoint in both. `scripts/provision.sh` installs it
  from Docker's own apt repository, with its CLI, containerd, and the Buildx and
  Compose plugins.
```

Lines 223-227 (Docker Compose):

```markdown
- **Docker Compose**: defines the stacks. `docker-compose.yml` is the development
  stack and the base for production. `docker-compose.override.yml`, which Compose loads
  only when no `-f` is given, adds the development file watch that syncs edits into the
  running containers; `npm run docker:up` watches through `up --watch`, which needs
  Compose 2.24.7 or newer. `docker/docker-compose.prod.yml` swaps the frontend for the
  nginx image, binds the backend and frontend to loopback ports for host nginx, and
  stops publishing the database port. Its `!reset` and `!override` tags need Compose
  2.24.4 or newer.
```

Lines 231-232 (`python:3.12-slim`):

```markdown
- **`python:3.12-slim`**: the backend image base. It installs only `requirements.txt`,
  plus watchdog when the dev stack builds it, so the image carries no lint, type-check,
  or test tools.
```

## Parallelism

Can be done in parallel; no file is shared between groups:

- A: `docker-compose.override.yml`, `docker/backend.Dockerfile`, `.dockerignore`,
  `scripts/tests/test-compose-config.sh`; check with
  `bash scripts/tests/test-compose-config.sh`
- B: `docker/entrypoint.sh`, `scripts/tests/test-entrypoint.sh`; check with
  `bash scripts/tests/test-entrypoint.sh`
- C: `scripts/up.sh`, `scripts/tests/test-up.sh`, `package.json`; check with
  `bash scripts/tests/test-up.sh`
- D: `README.md`, `ai/project.md`, `tools.md`; then `npx prettier --write README.md`

Must be sequential, after A to D: verification steps 1 to 3 (static), then the live
stack in steps 4 to 11, which share one running stack and must run one at a time, then
step 12.

## No other changes needed

- `docker-compose.yml`: line 30 already sets `FLASK_ENV: development` for the dev
  backend, line 25's `restart: unless-stopped` retries a backend whose import is broken,
  and `FLASK_RUN_HOST` (line 31) stays, though the entrypoint passes `--host` itself.
- `docker/docker-compose.prod.yml`: sets `FLASK_ENV: production` (line 18) and no
  backend build arguments.
- `docker/frontend.Dockerfile` and `vite.config.ts`: with no `server.hmr`, Vite's client
  opens its websocket on the page's own port, so HMR works through a shifted
  `FRONTEND_PORT`, and the Dockerfile's `--port 5173` already pins the container port.
- `docker/nginx.Dockerfile`: its builder's `COPY . .` now skips `src_back/uploads`,
  which the bundle never used. Excluding the folder also drops the tracked
  `src_back/uploads/.gitkeep` from the backend image; Docker creates the mount point for
  `uploads_data` in both stacks.
- `scripts/deploy.sh`, `scripts/backup.sh`: always pass `-f`, and production keeps
  gunicorn. `scripts/down.sh`, `scripts/docker-url.sh`, `scripts/worktree-setup.sh`:
  unchanged; the override is tracked, so every worktree has its own.
- `.github/workflows/ci.yml` and `scripts/tests/run-all.sh`: the scripts job runs
  `run-all.sh`, which finds the extended tests itself; no new script is added, so the
  syntax count stays 22.
- `.env.example`: its `FLASK_ENV` drives only `scripts/up.sh` and host-side runs; the
  dev backend's comes from `docker-compose.yml`.
- `requirements.txt`, `requirements-dev.txt`: watchdog arrives only through the build
  argument, and the image never installs `requirements-dev.txt`, so it gets no rule.
- No Python or TypeScript source changes, so no pytest or Vitest changes.
- For later issues, not this one: #22's unprivileged backend user will need the image to
  create and own `src_back/uploads`, since the image no longer contains it; #24 must
  build release images with `-f`, or they pick up the override's watchdog.

## Verification

1. `npm run test:scripts` prints `Checked the syntax of 22 scripts.`, then `PASS` for
   `test-compose-config.sh`, `test-entrypoint.sh`, and `test-up.sh`, and `SKIP` for
   `test-backup.sh` (it needs Linux), and exits 0.
2. Each new check catches its regression. Back the three files up first, because
   `git checkout` would also discard this change:
   `backup=$(mktemp -d) && cp docker-compose.override.yml scripts/up.sh
   docker/entrypoint.sh "$backup/"`. One at a time, restoring each from `$backup`
   before the next:
    - Change the `./migrations` rule's `action: sync` to `action: sync+restart`:
      `bash scripts/tests/test-compose-config.sh` prints `The dev configuration should
      have migrations synced without a restart.`
    - Change `path: ./tsconfig.test.json` to `path: ./tsconfig.tests.json`: the same test
      prints `The dev watch path <repo>/tsconfig.tests.json does not exist.`
    - Remove `--watch` from `up.sh`'s last `docker compose up` line:
      `bash scripts/tests/test-up.sh` prints
      `Missing /^docker compose up --build --watch$/ in commands`.
    - Change `= development ]` to `= dev ]` in `entrypoint.sh`:
      `bash scripts/tests/test-entrypoint.sh` fails with a diff whose `+` line is the
      gunicorn command.

    Afterwards `git status --short` lists the same files as before this step.
3. The production render the acceptance criteria name. The local `.env` supplies the
   variables the production override reads.

    ```bash
    prod() {
      docker compose -f docker-compose.yml -f docker/docker-compose.prod.yml "$@"
    }
    prod config |
      grep -E 'develop:|watch:|--reload|flask run|DEVELOPMENT_PACKAGES|watchdog'
    prod config | grep -E 'FLASK_ENV'
    prod config | grep -A 2 'entrypoint:'
    ```

    The first prints nothing (grep exits 1). The others print `FLASK_ENV: production`
    and the `/bin/sh docker/entrypoint.sh` entrypoint, under which the entrypoint
    starts gunicorn, as `test-entrypoint.sh`'s production cases prove; the render has no
    `command` to show it directly. Also `npx prettier --check docker-compose.override.yml
    README.md ai/project.md tools.md package.json` and `npm run lint:md` pass.
4. Start the live stack. Docker Desktop must be running; stop any dev stack first with
   `npm run docker:down`. `npm run docker:up` stays attached, so start it as a
   background command (Bash `run_in_background`) and read its output for Compose's watch
   messages. Then:

    ```bash
    npm run docker:url
    backend_port=$(grep -E '^BACKEND_PORT=' .env | cut -d= -f2)
    frontend_port=$(grep -E '^FRONTEND_PORT=' .env | cut -d= -f2)
    curl -fsS "http://localhost:$backend_port/api/health"
    docker compose logs backend | grep -E 'Serving Flask app|Restarting with watchdog'
    docker compose exec -T backend pip show watchdog | grep Version
    docker build -q -f docker/backend.Dockerfile -t frt-backend-check . > /dev/null
    docker run --rm --entrypoint pip frt-backend-check show watchdog
    docker rmi -f frt-backend-check
    time docker compose build
    ```

    Health prints `{"status":"ok"}`; the log shows `Serving Flask app` and
    `Restarting with watchdog (inotify)`, and no `Starting gunicorn`; the dev backend
    has `Version: 6.0.0`, while the plain build, which reads no override, reports
    `Package(s) not found: watchdog`. The throwaway tag keeps that build from replacing
    the dev images. Report the warm build's `real` time, the cost every start now pays.
5. A route edit applies with no command. Change `src_back/api/health.py:18` to
   `return jsonify({'status': 'ok', 'watch': 'check'})`; within five seconds
   `curl -fsS "http://localhost:$backend_port/api/health"` prints the new field. Then
   `git checkout -- src_back/api/health.py`, and it prints `{"status":"ok"}` again.
6. A broken import recovers, including when the fix is a new module, and across a
   restart:

    ```bash
    health="http://localhost:$backend_port/api/health"
    status() { curl -s -o /dev/null -w '%{http_code}\n' "$health"; }
    printf 'from src_back import watch_check_module  # noqa\n' >> src_back/api/health.py
    sleep 3; status                      # 500
    printf '"""Watch check."""\n' > src_back/watch_check_module.py
    sleep 3; status                      # 200: watchdog saw the new module
    rm src_back/watch_check_module.py
    sleep 3; status                      # 500 again: the deletion reached the backend
    git checkout -- src_back/api/health.py
    sleep 3; status                      # 200
    printf 'from src_back import watch_check_module  # noqa\n' >> src_back/api/health.py
    sleep 3; docker compose restart backend; sleep 10
    docker compose ps backend            # restarting or exited: db upgrade fails
    git checkout -- src_back/api/health.py
    for attempt in $(seq 1 24); do
      curl -fsS "$health" && break
      sleep 5
    done
    ```

    The last loop must print `{"status":"ok"}` within two minutes with no other
    command: Compose copies the fix into the stopped container, and the restart policy
    retries it.
7. A frontend edit reaches Vite, and the HMR channel answers on the host port. The host
   runs Node 20, which has no `WebSocket`, so curl checks each piece:

    ```bash
    client=$(curl -fsS "http://localhost:$frontend_port/@vite/client")
    printf '%s\n' "$client" | grep -c 'const hmrPort = null'
    token=$(printf '%s\n' "$client" | sed -n 's/^const wsToken = "\(.*\)";$/\1/p')
    curl -si --max-time 3 -H 'Connection: Upgrade' -H 'Upgrade: websocket' \
      -H 'Sec-WebSocket-Version: 13' -H 'Sec-WebSocket-Protocol: vite-hmr' \
      -H 'Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==' \
      "http://localhost:$frontend_port/?token=$token" | head -1
    curl -fsS "http://localhost:$frontend_port/src/pages/Login.tsx" > /dev/null
    sed -i '' 's/title="Sign in"/title="Sign in (watch check)"/' \
      src_front/src/pages/Login.tsx
    sleep 3
    curl -fsS "http://localhost:$frontend_port/src/pages/Login.tsx" |
      grep -c 'watch check'
    docker compose logs frontend | grep 'hmr update /src/pages/Login.tsx'
    git checkout -- src_front/src/pages/Login.tsx
    ```

    Expect `1`, then `HTTP/1.1 101 Switching Protocols`, then a count of at least 1,
    then an `hmr update` line. The browser check is the user's: with the page open at
    the `npm run docker:url` address, the same edit to `title="Sign in"`
    (`src_front/src/pages/Login.tsx:48`) changes the heading without a reload.
8. Deletion reaches the container, and host uploads never do:

    ```bash
    printf '"""Watch probe."""\n' > src_back/watch_probe.py && sleep 3
    docker compose exec -T backend test -f src_back/watch_probe.py && echo synced
    rm src_back/watch_probe.py && sleep 3
    docker compose exec -T backend test ! -e src_back/watch_probe.py && echo removed
    printf 'probe\n' > src_back/uploads/watch_probe.txt && sleep 3
    docker compose exec -T backend test ! -e src_back/uploads/watch_probe.txt &&
      echo 'kept out'
    rm src_back/uploads/watch_probe.txt
    ```

    It prints `synced`, `removed`, then `kept out`.
9. A host-side migration reaches the container without being applied, and a restart
   afterwards succeeds:

    ```bash
    docker compose logs backend | grep -c 'Running database migrations'
    .venv/bin/flask --app src_back.app db revision -m "watch check" && sleep 3
    docker compose exec -T backend sh -c 'ls migrations/versions | grep watch_check'
    docker compose exec -T backend flask --app src_back.app db current
    docker compose logs backend | grep -c 'Running database migrations'
    .venv/bin/flask --app src_back.app db upgrade
    docker compose restart backend && sleep 10
    curl -fsS "http://localhost:$backend_port/api/health"
    .venv/bin/flask --app src_back.app db downgrade
    rm migrations/versions/*_watch_check.py
    docker compose restart backend && sleep 10
    curl -fsS "http://localhost:$backend_port/api/health"
    ```

    `ls` lists the revision; `db current` still shows the previous head, not the new
    revision; the two counts match, so the container did not restart (Flask's reloader
    may log the new file, which is harmless); both health calls print
    `{"status":"ok"}`.
10. Dependency files rebuild their image. Append `# watch check` as a new last line of
    `requirements.txt`: the `npm run docker:up` output reports rebuilding `backend`,
    and health answers afterwards; `git checkout -- requirements.txt` triggers a second,
    cached rebuild. Then `printf '\n' >> package.json`: the output reports rebuilding
    `frontend`, and `npm run docker:url` answers afterwards. Remove that line with
    `sed -i '' '$d' package.json`, not `git checkout`, which would also undo this
    change's removal of `docker:up:build`.
11. A detached start says it is not watching. Stop the background `npm run docker:up`,
    then `npm run docker:down`, `npm run docker:up -- -d` (it prints `Starting detached,
    so not watching`), `npm run docker:url`, and `npm run docker:down`.
    `git status --short` shows only this change's files.
12. In one parallel batch: `npm run test`, `npm run lint -- --max-warnings=0`,
    `npm run lint:py`, `npm run lint:md`, `npx prettier --check .`, and
    `npm run test:scripts`; then `git diff --check`. Once the user pushes, CI's "Shell
    scripts" job shows `PASS` for all four tests. The PR description should say the
    issue's 2.22 Compose floor is 2.24.7 for `up --watch`, and that the production
    render proves gunicorn through `FLASK_ENV` and the entrypoint, not a `command`.
