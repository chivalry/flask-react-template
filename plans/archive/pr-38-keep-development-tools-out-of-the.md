# #11: Keep Development Tools out of the Backend Image and Trim the Frontend Image Build

## Context

`docker/backend.Dockerfile` installs all of `requirements.txt` (lines 5-6). That file
mixes the 12 runtime pins with six tools that only development and CI run
(`requirements.txt:14-19`): Ruff, pydoclint, basedpyright, pytest, pytest-flask, and
pytest-cov. In hukilau, generated from this template, they made the image 690 MB, about
270 MB of it basedpyright and the Node runtime it bundles. Separately,
`docker/nginx.Dockerfile:7` runs `npm run build`, which is `tsc -b && vite build`
(`package.json:8`). Every production frontend build therefore repeats the type check
that CI's `build` job already runs (`.github/workflows/ci.yml:137-138`), and on a
low-memory host that check alone took 30 minutes (chivalry/hukilau#14).

This ports hukilau's `7e5889d` (the requirements split, planned in its
`plans/pr-33-keep-lint-type-check-and-test-tools-out.md`) and the nginx changes from
`d553bdf` and `58ba36f`. Two facts keep it small:

- `docker/backend.Dockerfile` copies and installs `requirements.txt` by name (lines 5-6),
  so moving the tools into a new `requirements-dev.txt` is the whole image change. The
  Dockerfile is not edited.
- Nothing runs a development tool inside a Compose container. `package.json`,
  lint-staged, the Husky hooks, `.vscode`, and CI all call `.venv/bin/<tool>`. The
  backend container runs only `flask db upgrade`, the seed, and gunicorn
  (`docker/entrypoint.sh:5-17`, `package.json:29`). The devcontainer starts from
  `mcr.microsoft.com/devcontainers/python:3.12` (`.devcontainer/devcontainer.json:3`),
  not from `docker/backend.Dockerfile`.

Dropping `tsc -b` from the image loses no checking. CI's `build` job runs the same
`npm run build`, whose `tsc -b` covers the app, `vite.config.ts`, and the tests through
the three references in `tsconfig.json:3-7`. That job stays CI's only type check, since
ESLint is not type-aware (`eslint.config.js:11`).

Where hukilau's text describes hukilau, the port adapts it:

- The nginx comments drop "which CI sets to linux/arm64", because this template's CI
  builds no images until #24. They say the heap limit is for `scripts/deploy.sh`, which
  builds the image on the server.
- The `requirements-dev.txt` header and the README paragraph say the tools run from
  `.venv`, not "the host `.venv`" or "through package.json": in the devcontainer,
  `.venv` lives inside a container, and CI calls the tools directly.
- Hukilau's `--remove-orphans` and LAN-script edits belong to its #27 and stay out.
  `scripts/deploy.sh:132` already passes `--remove-orphans`.

## Branch

`issue-11-keep-development-tools-out-of-the` — already checked out; PR #38 exists.

## Change

**8 files, 7 edits and 1 new file**: `requirements.txt`, `requirements-dev.txt` (new),
`README.md`, `ai/project.md`, `scripts/worktree-setup.sh`,
`.devcontainer/devcontainer.json`, `.github/workflows/ci.yml`, and
`docker/nginx.Dockerfile`.

### `requirements.txt` — runtime packages only

Replace the whole file (lines 1-19) with hukilau's version. Every pin is unchanged;
lines 14-19 move to the new file below.

```text
# Runtime packages only: docker/backend.Dockerfile installs this file. The lint,
# type-check, and test tools live in requirements-dev.txt.
Flask==3.1.0
Flask-SQLAlchemy==3.1.1
# SQLAlchemy 2.1 defaults postgresql:// to psycopg 3; 2.0 keeps the psycopg2 driver.
SQLAlchemy==2.0.49
Flask-Migrate==4.0.7
Flask-Cors==5.0.0
Flask-Login==0.6.3
marshmallow==3.23.0
marshmallow-sqlalchemy==1.5.0
filetype==1.2.0
psycopg2-binary==2.9.10
python-dotenv==1.0.1
gunicorn==23.0.0
```

### `requirements-dev.txt` — new

End it with a newline (`.editorconfig:10`).

```text
# Development and CI tools on top of the runtime packages. The backend image never
# installs this file; every tool runs from .venv, locally and in CI.
-r requirements.txt
ruff==0.9.10
pydoclint==0.9.1
basedpyright==1.39.9
pytest==8.3.5
pytest-flask==1.3.0
pytest-cov==6.1.0
```

### `README.md` — install the dev file and say what the image holds

Line 27, in the Quick start block, becomes:

```text
.venv/bin/pip install -r requirements-dev.txt
```

After line 51 (the Docker paragraph ending `survive rebuilds.`), add a blank line and
this paragraph, so it sits before `## Worktrees`:

```markdown
The backend image installs only `requirements.txt`, the runtime packages. The lint,
type-check, and test tools come from `requirements-dev.txt` and run from `.venv`, never
inside the Compose containers.
```

### `ai/project.md` — name the two files

Replace lines 36-37, the paragraph under `## Commands`, with hukilau's:

```markdown
All commands run from the repo root via npm scripts. Python tooling always goes through
`.venv/bin/`, installed from `requirements-dev.txt`; `requirements.txt` holds only the
runtime packages and is the file `docker/backend.Dockerfile` installs.
```

### `scripts/worktree-setup.sh` — install the dev file

Line 105 becomes the line below. The comment block at lines 98-103 stays as it is.

```sh
.venv/bin/pip install -r requirements-dev.txt
```

### `.devcontainer/devcontainer.json` — install the dev file

Line 60 is the `postCreateCommand` string,
`python -m venv .venv && .venv/bin/pip install -r requirements.txt && npm install`.
Change its `requirements.txt` to `requirements-dev.txt`, and nothing else on the line.

### `.github/workflows/ci.yml` — install the dev file and key the pip cache on both

`setup-python`'s pip cache hashes only `requirements.txt` files unless told otherwise,
so a change to the dev file alone would restore a stale cache. After line 34
(`cache: 'pip'`), add hukilau's two lines at the same indentation:

```yaml
          # The default key hashes only requirements.txt; the glob adds the dev file.
          cache-dependency-path: requirements*.txt
```

Line 41 (43 after that insert) becomes:

```yaml
          .venv/bin/pip install -r requirements-dev.txt
```

The comment at lines 36-37 and every later step stay as they are.

### `docker/nginx.Dockerfile` — bundle on the build platform, cap the heap, skip `tsc`

Replace the builder stage (lines 1-7) so the whole file reads:

```dockerfile
# The bundle is static files, so the Node stage runs on the build machine's platform and
# only the nginx stage targets the image's platform.
FROM --platform=$BUILDPLATFORM node:22-slim AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
ARG VITE_API_URL
ARG NODE_BUILD_HEAP_MB=1024
# CI's build job type-checks the app and its tests, so the image only bundles. The heap
# limit guards small servers, where scripts/deploy.sh builds this image.
RUN NODE_OPTIONS="--max-old-space-size=${NODE_BUILD_HEAP_MB}" npx vite build

FROM nginx:1.27-alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY docker/nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
```

- BuildKit sets `$BUILDPLATFORM`. Compose builds with BuildKit, and
  `scripts/provision.sh:54-55` installs `docker-buildx-plugin` on the server.
- `npx vite build` finds the project's Vite, because `npm ci` installs devDependencies:
  nothing sets `NODE_ENV=production` before it.

## Parallelism

- **First, alone:** verification step 1 builds the "before" image. It must run before
  `requirements.txt` changes.
- **Then in parallel, sharing no files:**
    - A: `requirements.txt` and `requirements-dev.txt`
    - B: `README.md` and `ai/project.md`
    - C: `scripts/worktree-setup.sh`, `.devcontainer/devcontainer.json`, and
      `.github/workflows/ci.yml`
    - D: `docker/nginx.Dockerfile`
- **After A to D, in order:** verification steps 3 to 8. Step 6 rebuilds `.venv`, so
  step 7's gates run from the rebuilt venv.

## No other changes needed

- `docker/backend.Dockerfile`: lines 5-6 already copy and install only
  `requirements.txt`, so do not edit it. `requirements-dev.txt` never reaches an image:
  the backend Dockerfile copies files by name, and `nginx.Dockerfile`'s `COPY . .`
  feeds only the Node stage, whose files the nginx stage never copies.
- `package.json`, lint-staged (`package.json:39-44`), `.husky/pre-commit`,
  `.husky/pre-push`, `pyproject.toml`, `.vscode/`, `.dockerignore`, `scripts/up.sh`,
  `scripts/deploy.sh`, and both Compose files stay unchanged. Every tool still resolves
  from `.venv/bin/`.
- CI's `build` job keeps `npm run build`. It is the only type check in CI, and it now
  carries the check the image no longer runs.
- `docker/docker-compose.prod.yml:31-32` passes only `VITE_API_URL`, so the image builds
  with the 1024 MB default. `--build-arg NODE_BUILD_HEAP_MB=<mb>` overrides it, and a
  Compose `args:` entry is out of scope.
- Noticed, out of scope: `ARG VITE_API_URL` changes nothing in the production bundle.
  No code in `src_front/src` reads `import.meta.env`, and only the dev-server proxy uses
  the variable (`vite.config.ts:37-38`). The backend image also ships `src_back/tests/`
  through `COPY src_back/`, harmlessly, since nothing imports it at runtime.
- `tools.md` does not exist yet. #12 adds it after this issue and should name both
  requirements files. There is no Dependabot or Renovate config to update.
- No Python or TypeScript code changes, so there are no new pytest or Vitest tests.

## Verification

1. **Before any edit**, while the branch still equals `main` plus an empty commit, build
   the "before" backend image. Docker 29.7 and Compose 5.4 are installed, and the
   machine is arm64.

    ```bash
    docker build -f docker/backend.Dockerfile -t flask-react-template-backend:before .
    ```

2. Make edits A to D.
3. Build the slimmed image, compare sizes, and prove the tools are gone while the
   runtime imports remain:

    ```bash
    docker build -f docker/backend.Dockerfile -t flask-react-template-backend:after .
    docker images flask-react-template-backend --format '{{.Tag}}\t{{.Size}}'
    docker run --rm flask-react-template-backend:after python -c 'import pytest'
    docker run --rm flask-react-template-backend:after \
      python -c 'import gunicorn, psycopg2; from src_back.app import create_app'
    ```

    The first `docker run` must exit non-zero with
    `ModuleNotFoundError: No module named 'pytest'`; the second must exit 0.

4. **The dev stack runs from the slimmed image.** A plain `docker:up` would reuse the
   old `latest` image, so rebuild:

    ```bash
    npm run docker:up:build -- -d
    npm run docker:url
    curl -fsS "http://localhost:$(grep -E '^BACKEND_PORT=' .env | cut -d= -f2)/api/health"
    docker compose exec -T backend python -c 'import pytest'   # must fail
    ```

    If the stack was not running before this step, stop it with `npm run docker:down`.

5. **The production frontend builds without `tsc`.** Build it under a throwaway project
   name. Under the default name, the nginx image would take the dev frontend's
   `flask-react-template-frontend` tag, and the next `docker:up` without `--build`
   would start nginx in place of Vite.

    ```bash
    log=$(mktemp)
    docker compose -p flask-react-template-prod-check --progress plain \
      -f docker-compose.yml -f docker/docker-compose.prod.yml build frontend > "$log" 2>&1
    echo "exit=$?"
    grep -n 'npx vite build' "$log"   # the bundle step ran
    grep -c 'tsc -b' "$log"           # must print 0
    docker image rm flask-react-template-prod-check-frontend
    ```

6. **A venv filled from `requirements-dev.txt` alone.** The existing `.venv` already
   holds every tool from the old `requirements.txt`, so rebuild it from scratch:

    ```bash
    rm -rf .venv
    python3 -m venv .venv
    .venv/bin/pip install -r requirements-dev.txt
    ```

7. **Gates**, in one parallel batch, all from the rebuilt venv: `npm run test`,
   `npm run lint -- --max-warnings=0`, `npm run lint:py`, `npm run lint:md`, and
   `npx prettier --check .`. CI's frontend job runs Prettier, which checks the edited
   YAML, JSON, and Markdown. Steps 6 and 7 together cover the acceptance criterion that
   `lint:py` and `test:back` run from a venv filled by `requirements-dev.txt`.
8. **Record the sizes on PR #38** without losing its body, then remove the two
   measurement tags:

    ```bash
    body=$(mktemp)
    gh pr view 38 --json body --jq .body > "$body"
    cat >> "$body" <<'EOF'

    ## Backend image size

    | `docker/backend.Dockerfile`, local arm64 build | Size   |
    | ---------------------------------------------- | ------ |
    | Before (`main` at `b0903fb`)                   | <size> |
    | After                                          | <size> |
    EOF
    gh pr edit 38 --body-file "$body"
    docker image rm flask-react-template-backend:before flask-react-template-backend:after
    ```

    Fill both `<size>` cells from step 3's `docker images` output before running
    `gh pr edit`.
