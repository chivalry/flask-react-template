# Issue #16: Add a Staging Environment and Make Staging the Default Branch

## Context

Every merged PR goes straight to the only deployment, so nobody can try a feature first
and a migration first meets real data in production. This adds a staging environment:
a second clone and Compose project on the production host, with an environment badge,
its own session cookie, deploy guards, and a script that copies production into it. It
also makes `staging` the default branch, with releases merged into `main` by merge
commit.

References: hukilau `b9e43d3` for the application side and the branch rules (its
`EnvironmentBadge`, `utils/environment.ts`, `api/health.ts`, `app.py`, `conftest.py`, and
`ai/conventions.md` port almost verbatim); ranch-tracker `staging/scripts/` for the
deployment side; hukilau's `deploy-lan.sh` `copy_production` for a transactional copy.

Already in place, so no work: CI runs on every branch (`ci.yml:4-7`), and its fallow
audit falls back to the repository's default branch (`ci.yml:98`). The home-directory
skills already read the default branch. The template already takes ports, the project
name, gunicorn workers, and the nginx site from each clone's `.env`. PR #9, which the
issue says to settle first, merged on 2026-10-24.

## Branch

`issue-16-add-a-staging-environment-and-make`, already checked out. PR #50 exists and
targets `main`, which stays the default branch until the post-merge steps (section 13).

## Decisions settled while planning

1. PR #50 targets `main`. `staging` is cut from `main` after the merge (section 13). The
   PR's documentation describes the workflow from the moment the default changes.
2. `scripts/deploy.sh [--environment <name>]` defaults to `production`. The name must
   equal the clone's `APP_ENVIRONMENT`, where blank means production. The checked-out
   branch must equal `DEPLOY_BRANCH`, where blank means `main`. Both guards run before
   `git pull` and before anything changes.
3. A staging deploy skips the pre-migration dump, the timers, and the certbot renewal
   hook.
    - Staging's data is a disposable copy, and `backup.sh` would push the dump through
      the host-wide rclone remote, under whatever `BACKUP_PREFIX` staging's `.env`
      holds.
    - The hook is one host-wide file, which production's deploy installs. A staging
      deploy must not replace it with the staging branch's copy.
    - So a staging deploy changes no host-wide state but its own nginx site.
4. Staging's clone is `~/<APP_NAME>-staging`, and its `.env` sets
   `APP_NAME=<APP_NAME>-staging`. `remote-deploy.sh --environment staging` derives that
   path from the local `APP_NAME`.
5. `copy-production.sh` finds production through `PRODUCTION_DIR` in staging's `.env`.
   It restores a custom-format dump inside staging's database container, after
   `DROP SCHEMA public CASCADE`, in one transaction. This fixes two defects of a plain
   `pg_dump --clean | psql`:
    - Tables that only staging's newer migrations created would survive the copy. The
      entrypoint's `db upgrade` would then fail creating them, and the backend would
      restart in a loop.
    - A failed or truncated copy would leave a half-restored database.

   Uploads are copied with `find -delete` and `cp -a`, so dotfiles are copied too.
6. One `APP_TITLE` constant, in a new `src_front/src/appTitle.ts`, feeds the app bar
   and the badge's tab title.
7. `.env.example` lists every new key, the staging-only ones included.
   `ai/project.md` says it lists every variable. `test-provision.sh:156-164` also
   requires every key that `provision.sh` writes to appear there.
8. `certbot-setup.sh` uses `--nginx` when nginx is active and has at least one enabled
   site. Otherwise it keeps today's path: stop the web servers, then `--standalone`.
9. Chuck approved four more items on 2026-10-27:
    - `copy-production.sh` refuses until staging's installed nginx site asks for a
      password.
    - `install-backup.sh` refuses outside production, because its rclone remote is
      host-wide.
    - Rulesets on `main` and `staging`, added after the merge.
    - `~/.ai/standards/git.md` reads the default branch instead of `origin/main`.

## Change

**Files to edit (25)**:

- Backend: `src_back/app.py`, `src_back/api/health.py`,
  `src_back/tests/conftest.py`, `src_back/tests/test_health.py`,
  `src_back/tests/test_app.py`
- Frontend: `src_front/src/App.tsx`, `src_front/src/components/layout/AppShell.tsx`,
  `src_front/src/test/App.test.tsx`
- Config and scripts: `docker/docker-compose.prod.yml`, `.env.example`,
  `package.json`, `scripts/deploy.sh`, `scripts/nginx-ssl.conf.template`,
  `scripts/certbot-setup.sh`, `scripts/remote-deploy.sh`,
  `scripts/worktree-setup.sh`, `scripts/provision.sh`, `scripts/install-backup.sh`
- Script tests: `scripts/tests/test-deploy.sh`, `test-nginx-site.sh`,
  `test-provision.sh`, `test-compose-config.sh`, `test-install-backup.sh`
- Docs: `README.md`, `ai/conventions.md`, `ai/project.md`, `ai/backups.md`,
  `ai/tls.md`, `ai/auth.md`, `ai/domain.md`, `tools.md`, `AGENTS.md`,
  `.claude/CLAUDE.md`

**Files to create (14)**:

- `src_front/src/appTitle.ts`, `src_front/src/utils/environment.ts`,
  `src_front/src/api/health.ts`,
  `src_front/src/components/layout/EnvironmentBadge.tsx`
- Frontend tests: `src_front/src/test/api/health.test.ts`,
  `src_front/src/test/utils/environment.test.ts`,
  `src_front/src/test/components/layout/EnvironmentBadge.test.tsx`
- Scripts: `.env.staging.example`, `scripts/copy-production.sh` (mode 755)
- Script tests: `scripts/tests/test-copy-production.sh`,
  `test-remote-deploy.sh`, `test-certbot-setup.sh`, `test-worktree-setup.sh` (mode 644)
- `ai/staging.md`

### 1. Backend

**`src_back/app.py`**: add this function after `_configure_application`, which ends at
line 144, and before `_guard_secret_key` at line 147. Call it in `create_app` right
after `_configure_application(app)` (line 93), before the overrides are applied (line
94). A separate function keeps `_configure_application`, now 38 lines, clear of the
50-line cap.

```python
def _configure_environment(app: Flask) -> None:
    """Name the deployment, and give any but production its own session cookie.

    ``APP_ENVIRONMENT`` is ``production`` when unset or blank, and ``/api/health``
    reports it so the frontend can badge every page outside production. Browsers keep
    cookies per host name, not per port, so another environment reached under
    production's host name would otherwise overwrite production's session cookie.

    Args:
        app: The application being configured.
    """
    environment = os.environ.get('APP_ENVIRONMENT') or 'production'
    app.config['APP_ENVIRONMENT'] = environment
    if environment != 'production':
        app.config['SESSION_COOKIE_NAME'] = f'{environment}_session'
```

**`src_back/api/health.py`**: replace the whole file.

```python
"""Unauthenticated liveness endpoint, which also names the deployment environment."""

from flask import Blueprint, Response, current_app, jsonify

bp = Blueprint('health', __name__)


@bp.get('/health')
def health() -> Response:
    """Report that the application is serving requests, and in which environment.

    Deliberately does not touch the database, so it stays a pure liveness
    signal rather than a readiness check. It answers without a session, so the
    sign-in page can show the environment badge too.

    Returns:
        A JSON body of ``{'status': 'ok', 'environment': <name>}``, where the name
        comes from ``APP_ENVIRONMENT`` and defaults to ``production``.
    """
    environment = current_app.config['APP_ENVIRONMENT']
    return jsonify({'status': 'ok', 'environment': environment})
```

**`src_back/tests/conftest.py`**: add this autouse fixture before the `app` fixture
(line 54). It follows the precedent in `test_seed.py:23-28`. `test_auth.py` reads the
`session` cookie at lines 30, 236, 327, and 353, and many `test_app.py` tests call
`create_app()` without the `app` fixture, so the fixture must cover every test.

```python
@pytest.fixture(autouse=True)
def _clear_app_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    # src_back.app loads .env at import; a developer's APP_ENVIRONMENT would rename the
    # session cookie that test_auth.py reads.
    monkeypatch.delenv('APP_ENVIRONMENT', raising=False)
```

**`src_back/tests/test_health.py`**: replace the whole file.

```python
import pytest
from flask.testing import FlaskClient

from src_back.app import create_app


def test_health(client: FlaskClient) -> None:
    response = client.get('/api/health')
    assert response.status_code == 200
    assert response.get_json() == {'status': 'ok', 'environment': 'production'}


@pytest.mark.parametrize(
    ('environment', 'reported'),
    [('', 'production'), ('production', 'production'), ('staging', 'staging')],
)
def test_health_reports_the_environment(
    monkeypatch: pytest.MonkeyPatch, environment: str, reported: str
) -> None:
    monkeypatch.setenv('APP_ENVIRONMENT', environment)
    app = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:'})
    assert app.test_client().get('/api/health').get_json()['environment'] == reported
```

**`src_back/tests/test_app.py`**: add this test after
`test_webauthn_rp_name_falls_back_to_app_name_then_the_template_name`, which ends at
line 373.

```python
@pytest.mark.parametrize(
    ('environment', 'cookie_name'),
    [('', 'session'), ('production', 'session'), ('staging', 'staging_session')],
)
def test_only_production_keeps_flasks_session_cookie_name(
    monkeypatch: pytest.MonkeyPatch, environment: str, cookie_name: str
) -> None:
    monkeypatch.setenv('APP_ENVIRONMENT', environment)
    app = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:'})
    assert app.config['SESSION_COOKIE_NAME'] == cookie_name
```

### 2. Frontend

**`src_front/src/appTitle.ts`** (new):

```ts
/** @file The application's display name, shown in the app bar and the browser tab. */

/** The name `index.html`'s `<title>` also carries; rename the two together. */
export const APP_TITLE = 'Flask React Template'
```

**`src_front/src/utils/environment.ts`** (new). It is hukilau's file, verbatim.

```ts
/** @file The label a deployment environment shows in the UI. */

/**
 * Name a non-production environment for the badge and the tab title.
 *
 * @param environment - The name `/api/health` reports, or undefined until it loads.
 * @returns The name in capitals, or null for production and while it is unknown.
 */
export function environmentLabel(environment: string | undefined): string | null {
    if (!environment || environment === 'production') return null
    return environment.toUpperCase()
}
```

**`src_front/src/api/health.ts`** (new). It follows `api/auth.ts`, with an unexported
response interface, as `LogoutResponse` is there.

```ts
/** @file The unauthenticated health check, which names the deployment environment. */

import client from './client'

/** The body the health endpoint returns. */
interface HealthResponse {
    status: string
    environment: string
}

/**
 * Ask the backend whether it is serving, and which environment it belongs to.
 *
 * @returns The response wrapping the health body.
 */
export const getHealth = () => client.get<HealthResponse>('/health')
```

**`src_front/src/components/layout/EnvironmentBadge.tsx`** (new). It is hukilau's
component, but the title comes from `APP_TITLE`.

```tsx
/** @file Badge and tab title marking a non-production deployment, such as staging. */

import { Chip } from '@mui/material'
import { useEffect, useState } from 'react'

import { getHealth } from '../../api/health'
import { APP_TITLE } from '../../appTitle'
import { environmentLabel } from '../../utils/environment'

/**
 * Mark every page of a non-production deployment.
 *
 * A fixed badge names the environment and the tab title starts with it. Production,
 * and a health check that is still loading or has failed, render nothing, so
 * production is never mislabeled. The name is fetched once into local state rather
 * than a query: `useSessionQueryCache` clears every query when the account changes,
 * which would cancel the fetch during sign-in.
 *
 * @returns The badge, or null.
 */
export default function EnvironmentBadge() {
    const [environment, setEnvironment] = useState<string>()
    const label = environmentLabel(environment)

    useEffect(() => {
        void getHealth()
            .then((response) => setEnvironment(response.data.environment))
            .catch(() => undefined)
    }, [])

    useEffect(() => {
        document.title = label ? `${label} · ${APP_TITLE}` : APP_TITLE
    }, [label])

    if (!label) return null
    return (
        <Chip
            role="status"
            label={label}
            color="warning"
            sx={{
                position: 'fixed',
                left: 12,
                bottom: 12,
                zIndex: 'tooltip',
                fontWeight: 700,
                pointerEvents: 'none',
            }}
        />
    )
}
```

**`src_front/src/components/layout/AppShell.tsx`**: replace the literal
`Flask React Template` at line 145 with `{APP_TITLE}`. Add
`import { APP_TITLE } from '../../appTitle'` to the local imports (lines 12-13).

**`src_front/src/App.tsx`**:

- Line 1: change the file comment to
  `/** @file Route table for the application, and the environment badge. */`.
- Import `EnvironmentBadge from './components/layout/EnvironmentBadge'` beside
  `AppShell` (line 7).
- In the JSDoc at lines 18-34, add a sentence: "Outside production,
  {@link EnvironmentBadge} marks every page, the sign-in page included." Change
  `@returns` to `The route table and the environment badge.`
- Return `<>` `<EnvironmentBadge />` followed by the existing `<Suspense>` block
  (lines 44-62) `</>`. The badge must sit outside `Suspense`. That `Suspense` is the
  only boundary around the lazy Login and Register pages, so anything inside it waits
  for their chunks.

**`src_front/src/test/api/health.test.ts`** (new). It follows `test/api/auth.test.ts`:

```ts
import type { AxiosResponse } from 'axios'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import client from '../../api/client'
import { getHealth } from '../../api/health'

vi.mock('../../api/client')

describe('health api', () => {
    beforeEach(() => {
        vi.resetAllMocks()
    })

    it('reads the unauthenticated health check', async () => {
        vi.mocked(client.get).mockResolvedValue({
            data: { status: 'ok', environment: 'staging' },
        } as AxiosResponse)

        const response = await getHealth()

        expect(client.get).toHaveBeenCalledWith('/health')
        expect(response.data.environment).toBe('staging')
    })
})
```

**`src_front/src/test/utils/environment.test.ts`** (new). It is hukilau's file,
verbatim. It checks `'STAGING'` for `'staging'`, and null for `'production'`,
`undefined`, and `''`.

**`src_front/src/test/components/layout/EnvironmentBadge.test.tsx`** (new). It is
hukilau's four cases, with two changes:

- Import `APP_TITLE` from `../../../appTitle`, and expect `` `STAGING · ${APP_TITLE}` ``
  and `APP_TITLE` instead of the literal `Hukilau`.
- `beforeEach` sets `document.title = ''`, not the app title. The production, pending,
  and failed cases then prove the title effect ran: jsdom starts with an empty title,
  and Testing Library never resets it.

The four cases are:

- staging: `findByRole('status')` has the text `STAGING`; the title becomes
  `STAGING · ${APP_TITLE}`; `getHealth` is called once.
- production: no `status` role, and the title is `APP_TITLE`.
- pending, with `mockReturnValue(new Promise(() => undefined))`: no badge, and the
  title is `APP_TITLE`.
- rejected, with `mockRejectedValue(new Error('Network Error'))`: no badge, and the
  title is `APP_TITLE`. Without the `.catch`, this case fails on an unhandled
  rejection.

**`src_front/src/test/App.test.tsx`**:

- Add `vi.mock('../api/health')` beside the other mocks (lines 14-15), and import
  `getHealth`.
- In `beforeEach`, add
  `vi.mocked(getHealth).mockReturnValue(new Promise(() => undefined))`. Without it, the
  automock returns `undefined`, and the badge's `getHealth().then` throws.
- Add this test:

```tsx
it('shows the environment badge on the sign-in page', async () => {
    signedOut()
    vi.mocked(getHealth).mockResolvedValue({
        data: { status: 'ok', environment: 'staging' },
    } as AxiosResponse)

    renderAppAtPath('/login')

    expect(await screen.findByRole('status')).toHaveTextContent('STAGING')
    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument()
})
```

The literal title stays in `App.test.tsx:79` and `AppShell.test.tsx:52`. Both tests
pass unchanged. The README rename checklist names them beside `appTitle.ts`.

### 3. Compose and environment files

**`docker/docker-compose.prod.yml`**: after `FLASK_ENV: production` (line 18), add
`APP_ENVIRONMENT: ${APP_ENVIRONMENT:-}`, indented like it. Blank stays blank, and the
app treats blank as production, so the default lives in one place. Inside a container,
`load_dotenv()` finds no `.env`, because `.dockerignore:13` excludes it. This line is
therefore the only way the value reaches the backend.

**`.env.example`**: after `FRONTEND_HOST_PORT=8080` (line 65), inside the "Production
only" section, add:

```text
# The deployment this clone serves, and the branch it deploys. APP_ENVIRONMENT blank or
# production is production; any other value (staging) badges every page and names its
# own session cookie. scripts/deploy.sh refuses a clone on any branch but DEPLOY_BRANCH.
APP_ENVIRONMENT=
DEPLOY_BRANCH=main

# --- Staging only (.env.staging.example is a whole staging .env) ---------------
# STAGING_HTPASSWD names an htpasswd file; host nginx then asks for a password before
# serving anything. PRODUCTION_DIR is the clone scripts/copy-production.sh copies from.
STAGING_HTPASSWD=
PRODUCTION_DIR=
```

**`.env.staging.example`** (new):

```text
# Staging: a second clone and Compose project beside production on the same server
# (ai/staging.md). Copy this file to .env in the staging clone, chmod 600 it, and fill
# in every blank. Generate each secret with `openssl rand -hex 32`; none may match
# production's.

# --- Environment and branch -----------------------------------------------------
# Anything but production badges every page and names its own session cookie.
# scripts/deploy.sh refuses a clone on any branch but DEPLOY_BRANCH.
APP_ENVIRONMENT=staging
DEPLOY_BRANCH=staging

# --- Identity -------------------------------------------------------------------
# Production's APP_NAME plus -staging. It names this clone under $HOME, where
# `npm run deploy:staging` looks for it, the nginx site, and the log directory.
# COMPOSE_PROJECT_NAME pins this stack's own volumes; it must differ from production's.
APP_NAME=flask-react-template-staging
COMPOSE_PROJECT_NAME=flask-react-template-staging
DOMAIN=
# Let's Encrypt registration address for scripts/certbot-setup.sh (or pass --email).
CERTBOT_EMAIL=
# The production clone scripts/copy-production.sh copies from.
PRODUCTION_DIR=/root/flask-react-template

# --- PostgreSQL (db service) and the URL Flask uses to reach it -----------------
# The role and database names match production's, so a copy of production's database
# keeps its owner. The password differs; repeat it inside DATABASE_URL.
POSTGRES_USER=app
POSTGRES_PASSWORD=
POSTGRES_DB=app
DATABASE_URL=postgresql://app:<POSTGRES_PASSWORD>@db:5432/app

# --- Flask ----------------------------------------------------------------------
# CORS_ALLOWED_ORIGINS and PUBLIC_BASE_URL are both https://<DOMAIN>.
SECRET_KEY=
FLASK_ENV=production
CORS_ALLOWED_ORIGINS=
PUBLIC_BASE_URL=
WEBAUTHN_RP_NAME=Flask React Template (staging)
SESSION_COOKIE_SECURE=true
SESSION_COOKIE_SAMESITE=Strict
GUNICORN_WORKERS=2

# --- First admin (src_back/seed.py) ---------------------------------------------
ADMIN_EMAIL=
ADMIN_PASSWORD=

# --- Loopback ports, shifted past production's 5000 and 8080 ---------------------
BACKEND_PORT=5001
FRONTEND_HOST_PORT=8081

# --- Frontend build arg ---------------------------------------------------------
VITE_API_URL=http://backend:5000

# --- Access ---------------------------------------------------------------------
# The htpasswd file host nginx checks before it serves any page or API call;
# ai/staging.md shows how to make one.
STAGING_HTPASSWD=/etc/nginx/flask-react-template-staging.htpasswd
```

**`package.json`**: after `"deploy"` (line 32), add
`"deploy:staging": "bash scripts/remote-deploy.sh --environment staging"`.

### 4. `scripts/deploy.sh`

1. **Header**: replace lines 2-14 with a header that states the following:
    - The invocation becomes `bash ~/<APP_NAME>/scripts/deploy.sh --environment <name>`,
      through `npm run deploy` or `npm run deploy:staging`.
    - `--environment` defaults to production. It must match `APP_ENVIRONMENT`, where
      blank means production. The clone must be on `DEPLOY_BRANCH`, where blank means
      `main`. So a staging clone holding production's `.env`, or a production clone
      switched to `staging`, is refused before anything changes.
    - The steps list says: the pre-migration backup, the certbot renewal hook, and the
      systemd units are production's alone; the nginx site sits behind basic auth when
      `STAGING_HTPASSWD` is set.

   Mention no path under `/etc/` other than `/etc/letsencrypt`, `/etc/nginx`, and
   `/etc/systemd/system`. `test-deploy.sh:47-48` fails on any other path.
2. **Arguments**: after `set -euo pipefail` (line 15), add:

    ```bash
    usage() {
      echo "usage: bash scripts/deploy.sh [--environment <name>]"
      exit 1
    }
    REQUESTED_ENVIRONMENT=production
    while [ $# -gt 0 ]; do
      case "$1" in
        --environment)
          [ $# -ge 2 ] && [ -n "$2" ] || usage
          REQUESTED_ENVIRONMENT=$2
          shift 2
          ;;
        --environment=?*) REQUESTED_ENVIRONMENT=${1#--environment=}; shift ;;
        *) usage ;;
      esac
    done
    ```

3. **Environment and htpasswd**: after the `PUBLIC_BASE_URL` check (line 43), add the
   block below. It runs no commands, so `test-deploy.sh` cases 11-12 still see none.

    ```bash
    APP_ENVIRONMENT="$(get APP_ENVIRONMENT)"
    APP_ENVIRONMENT="${APP_ENVIRONMENT:-production}"
    if [ "$APP_ENVIRONMENT" != "$REQUESTED_ENVIRONMENT" ]; then
      echo "ERROR: asked to deploy $REQUESTED_ENVIRONMENT, but $REPO_DIR/.env deploys"
      echo "       $APP_ENVIRONMENT; pass --environment $APP_ENVIRONMENT for that."
      exit 1
    fi
    DEPLOY_BRANCH="$(get DEPLOY_BRANCH)"
    DEPLOY_BRANCH="${DEPLOY_BRANCH:-main}"
    STAGING_HTPASSWD="$(get STAGING_HTPASSWD)"
    if [ -n "$STAGING_HTPASSWD" ] && [ ! -f "$STAGING_HTPASSWD" ]; then
      echo "ERROR: STAGING_HTPASSWD names $STAGING_HTPASSWD, which does not exist."
      echo "       Create it (ai/staging.md) or clear the setting. Refusing to deploy."
      exit 1
    fi
    ```

4. **Branch guard**: insert it after the certificate check (line 113), before the
   `Deploying` echo (line 115). It must stay after the volume and certificate checks,
   because `test-deploy.sh` cases 6 and 7 refute any `git` call before those fail.

    ```bash
    # The clone deploys only the branch its .env names, so the production clone never
    # deploys staging's commits, or the reverse.
    CURRENT_BRANCH="$(git symbolic-ref --quiet --short HEAD)" ||
      CURRENT_BRANCH='a detached HEAD'
    if [ "$CURRENT_BRANCH" != "$DEPLOY_BRANCH" ]; then
      echo "ERROR: $REPO_DIR is on $CURRENT_BRANCH, but its .env deploys $DEPLOY_BRANCH."
      echo "       Run 'git switch $DEPLOY_BRANCH' there first. Refusing to deploy."
      exit 1
    fi
    ```

5. **Deploying line**: line 115 becomes
   `echo "==> Deploying '$APP_NAME' ($APP_ENVIRONMENT) for https://$DOMAIN"`.
6. **Pre-migration backup** (lines 125-140): add a first branch to the `if`, and extend
   the comment with the reason (decision 3).

    ```bash
    if [ "$APP_ENVIRONMENT" != production ]; then
      echo "==> $APP_ENVIRONMENT deploys take no pre-migration backup."
    elif [ "$FIRST_DEPLOY" = 0 ]; then
      # unchanged: up -d db, wait_for_db, backup.sh --pre-migration --label ...
    else
      echo "==> First deploy: no database to back up yet."
    fi
    ```

   The uploads `chown` (lines 147-154) stays for every environment.
7. **nginx site** (lines 169-174): before the `sed`, add the block below. Then add
   `-e "s|__BASIC_AUTH__|$BASIC_AUTH|g"` to the `sed`.

    ```bash
    # STAGING_HTPASSWD puts the whole site behind a password; both directives go on the
    # template's basic-auth line, which is left blank otherwise.
    BASIC_AUTH=''
    if [ -n "$STAGING_HTPASSWD" ]; then
      BASIC_AUTH="auth_basic \"$APP_NAME\"; auth_basic_user_file $STAGING_HTPASSWD;"
    fi
    ```

8. **Renewal hook and systemd units** (lines 183-211): wrap everything from the
   renewal-hook echo (line 183) through `enable --now` (line 211) in
   `if [ "$APP_ENVIRONMENT" = production ]; then ... else ... fi`, indented two spaces.
    - Extend the comment. Production's `cert-check` covers every certificate on the
      host. Its certbot drop-in fires on any failed renewal. Its renewal hook, one
      host-wide file, reloads nginx after any renewal, staging's included, so a staging
      deploy must not replace it with the staging branch's copy. Staging's data is not
      backed up.
    - The `else` branch prints:

        ```bash
        echo "==> $APP_ENVIRONMENT installs no renewal hook, backups, restore drill, or"
        echo "    certificate monitoring; production's cover this host's certificates."
        ```

    - A staging deploy thus changes no host-wide state except its own nginx site, and
      the `rm` of the stock default site, which production has already removed.
9. **Last line**: `echo "==> Deployment complete ($APP_ENVIRONMENT): https://$DOMAIN"`.

### 5. `scripts/nginx-ssl.conf.template`

- **Header** (lines 1-4): after the four placeholders, add: "and fills the basic-auth
  line in the HTTPS server from `STAGING_HTPASSWD`". Do not write the placeholder's
  literal name in a comment, because `sed` would substitute the directives into the
  comment.
- **Directive line**: after `client_max_body_size 25m;` (line 40), add a blank line and
  the four lines below. In the file, each is indented 4 spaces, like line 40.
  `test-deploy.sh` compares the rendered line exactly.

```nginx
    # deploy.sh fills the next line with the basic-auth directives when .env sets
    # STAGING_HTPASSWD, so every page and API call asks for a password, and leaves it
    # blank otherwise. nginx's 401 carries the security headers above as well.
    __BASIC_AUTH__
```

The comment must not name the `auth_basic` directives. `deploy.sh` renders comments
too, so naming them would put the words into every installed site. A check that
greps for them would then pass on every server.

Renewals are unaffected. Basic auth sits only in the 443 server. certbot's nginx
authenticator answers the HTTP challenge in the port-80 server, by inserting a
`rewrite ... break` above its `return 301`.

### 6. `scripts/certbot-setup.sh`

- **Header** (lines 2-17): add that a later certificate on a host whose nginx already
  serves a site, such as staging's beside production, goes through the running nginx
  with `--nginx`. Nothing is stopped and production stays up. The first certificate on
  a bare host keeps the standalone path and the renewal switch.
- **Restore loop** (lines 72-79): make it safe for an empty array under `set -u` in
  bash 3.2, the bash `test-certbot-setup.sh` runs under on macOS:
  `for service in ${STOPPED_SERVICES[@]+"${STOPPED_SERVICES[@]}"}; do`. Linux
  behavior does not change.
- **Request** (lines 82-92): replace the stop loop and the certbot call with:

    ```bash
    # nginx_serves_a_site -> nginx is running with at least one enabled site, as on a
    # host that already serves production. provision.sh removes the default site, so a
    # bare host has none and still needs standalone.
    nginx_serves_a_site() {
      sudo systemctl is-active --quiet nginx &&
        [ -n "$(ls -A /etc/nginx/sites-enabled 2>/dev/null)" ]
    }

    if nginx_serves_a_site; then
      echo "==> nginx already serves a site; requesting the certificate through it..."
      sudo certbot certonly --nginx -d "$DOMAIN" \
        --non-interactive --agree-tos -m "$EMAIL"
    else
      echo "==> Stopping any service on port 80..."
      # the existing for-loop over nginx and apache2, unchanged
      echo "==> Requesting certificate..."
      sudo certbot certonly --standalone -d "$DOMAIN" \
        --non-interactive --agree-tos -m "$EMAIL"
    fi
    ```

The renewal switch and its check (lines 94-102) stay as they are. On the `--nginx`
path, the `sed` changes nothing and the check passes.

### 7. `scripts/copy-production.sh` (new, mode 755)

```bash
#!/usr/bin/env bash
# Replace this staging clone's database and uploads with copies of production's, to
# rehearse a release against real rows. Run as root on the server, from inside the
# staging clone:
#   bash scripts/copy-production.sh [--yes]
#
# PRODUCTION_DIR in this clone's .env names the production clone. The script refuses
# unless this .env says APP_ENVIRONMENT=staging, production's .env deploys production,
# the two COMPOSE_PROJECT_NAME values differ, both stacks use the same POSTGRES_USER and
# POSTGRES_DB (so the copy keeps its owner), staging's installed nginx site asks for a
# password, and both uploads volumes exist. It asks before changing anything unless
# --yes is given.
#
# Production is only read: pg_dump runs while it serves, and its uploads volume is
# mounted read-only. Staging's backend stops for the copy and starts again however the
# script ends; its entrypoint then migrates the copy to staging's schema. The database
# is replaced in one transaction, so a failed copy leaves staging's as it was.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
cd "$REPO_DIR"

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

# get KEY FILE -> the last KEY= value in FILE, or nothing.
get() { grep -E "^$1=" "$2" 2>/dev/null | tail -1 | cut -d= -f2- || true; }

ASSUME_YES=0
while [ $# -gt 0 ]; do
  case "$1" in
    --yes) ASSUME_YES=1; shift ;;
    *) fail 'usage: bash scripts/copy-production.sh [--yes]' ;;
  esac
done

[ -f .env ] || fail "no .env in $REPO_DIR; set staging up first (ai/staging.md)."
ENVIRONMENT="$(get APP_ENVIRONMENT .env)"
[ "$ENVIRONMENT" = staging ] ||
  fail "$REPO_DIR/.env deploys ${ENVIRONMENT:-production};" \
    'only staging copies production.'
PRODUCTION_DIR="$(get PRODUCTION_DIR .env)"
[ -n "$PRODUCTION_DIR" ] || fail "PRODUCTION_DIR is empty in $REPO_DIR/.env."
PRODUCTION_ENV="$PRODUCTION_DIR/.env"
[ -f "$PRODUCTION_ENV" ] || fail "no .env in $PRODUCTION_DIR (PRODUCTION_DIR)."
PRODUCTION_ENVIRONMENT="$(get APP_ENVIRONMENT "$PRODUCTION_ENV")"
[ "${PRODUCTION_ENVIRONMENT:-production}" = production ] ||
  fail "$PRODUCTION_ENV deploys $PRODUCTION_ENVIRONMENT, not production."
PROJECT="$(get COMPOSE_PROJECT_NAME .env)"
PRODUCTION_PROJECT="$(get COMPOSE_PROJECT_NAME "$PRODUCTION_ENV")"
if [ -z "$PROJECT" ] || [ -z "$PRODUCTION_PROJECT" ] ||
  [ "$PROJECT" = "$PRODUCTION_PROJECT" ]; then
  fail 'staging and production need different COMPOSE_PROJECT_NAME values.'
fi
POSTGRES_USER="$(get POSTGRES_USER .env)"
POSTGRES_DB="$(get POSTGRES_DB .env)"
if [ -z "$POSTGRES_USER" ] || [ -z "$POSTGRES_DB" ] ||
  [ "$POSTGRES_USER" != "$(get POSTGRES_USER "$PRODUCTION_ENV")" ] ||
  [ "$POSTGRES_DB" != "$(get POSTGRES_DB "$PRODUCTION_ENV")" ]; then
  fail "POSTGRES_USER and POSTGRES_DB must match production's," \
    'so the copy keeps its owner.'
fi
BACKEND_PORT="$(get BACKEND_PORT .env)"
BACKEND_PORT="${BACKEND_PORT:-5000}"
PRODUCTION_UPLOADS="${PRODUCTION_PROJECT}_uploads_data"
UPLOADS="${PROJECT}_uploads_data"

# The copy holds every account's email and password hash, so staging's installed
# nginx site must ask for a password before the copy is made.
APP_NAME="$(get APP_NAME .env)"
[ -n "$APP_NAME" ] || fail "APP_NAME is empty in $REPO_DIR/.env."
SITE="/etc/nginx/sites-available/$APP_NAME"
grep -Eq '^[^#]*auth_basic_user_file[[:space:]]' "$SITE" 2>/dev/null ||
  fail "staging's nginx site ($SITE) asks for no password; set STAGING_HTPASSWD" \
    "and deploy staging first (ai/staging.md)."

# docker run -v would create a missing volume empty, so both must already exist.
for volume in "$PRODUCTION_UPLOADS" "$UPLOADS"; do
  docker volume inspect "$volume" >/dev/null 2>&1 ||
    fail "volume $volume does not exist; deploy both stacks first."
done

compose() {
  docker compose -f docker-compose.yml -f docker/docker-compose.prod.yml \
    --env-file .env "$@"
}
production_compose() {
  docker compose -f "$PRODUCTION_DIR/docker-compose.yml" \
    -f "$PRODUCTION_DIR/docker/docker-compose.prod.yml" --env-file "$PRODUCTION_ENV" "$@"
}

# Poll staging's health endpoint every 2 s for up to 2 minutes, as deploy.sh does.
wait_for_backend() {
  local attempt
  for attempt in $(seq 1 60); do
    if curl -fsS "http://127.0.0.1:$BACKEND_PORT/api/health" >/dev/null 2>&1; then
      return 0
    fi
    echo "   waiting for the backend ($attempt/60)..."
    sleep 2
  done
  echo "ERROR: staging's backend did not become healthy within 2 minutes. Recent log:"
  compose logs --tail 50 backend || true
  exit 1
}

echo "This replaces staging's database and uploads (project $PROJECT) with copies of"
echo "production's (project $PRODUCTION_PROJECT in $PRODUCTION_DIR)."
if [ "$ASSUME_YES" = 0 ]; then
  printf 'Continue? [y/N] '
  read -r answer || true
  case "$answer" in
    y | Y) ;;
    *) echo 'Nothing changed.'; exit 1 ;;
  esac
fi

# Runs inside staging's db container. pg_restore turns the dump into SQL first, so a
# truncated dump stops before psql runs, and psql replaces the public schema in one
# transaction, so any error leaves staging's database as it was. Dropping the schema,
# rather than pg_dump --clean, also removes tables only staging's newer migrations
# made; the backend's entrypoint makes them again from the copy.
RESTORE='set -e
sql=$(mktemp)
trap "rm -f $sql" EXIT
pg_restore --no-owner --file="$sql"
{
  echo "SET client_min_messages = warning;"
  echo "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
  cat "$sql"
} | psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" --single-transaction \
  --file=- -v ON_ERROR_STOP=1 --quiet --output=/dev/null'

echo "==> Stopping staging's backend..."
compose stop backend
# From here on, staging's backend starts again however the script ends.
trap 'compose start backend >/dev/null 2>&1 || true' EXIT

echo "==> Copying production's database into staging..."
production_compose exec -T db pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc |
  compose exec -T db sh -c "$RESTORE" ||
  fail "copying the database failed; staging's database is unchanged."

echo "==> Copying production's uploads into staging..."
docker run --rm -v "$PRODUCTION_UPLOADS:/from:ro" -v "$UPLOADS:/to" alpine \
  sh -c 'find /to -mindepth 1 -delete && cp -a /from/. /to/' ||
  fail "copying the uploads failed; staging holds production's database."

trap - EXIT
echo "==> Starting staging's backend; its entrypoint migrates the copy..."
compose start backend
wait_for_backend
echo "==> Staging now holds a copy of production."
```

Host nginx sends `/api` and `/uploads` straight to the backend's loopback port.
Restarting the backend therefore never strands the frontend container's proxy, and the
frontend needs no restart.

The site check reads the installed file, not `.env`, because only a deploy puts
`STAGING_HTPASSWD` into the site that nginx serves. Its pattern skips commented lines.

`RESTORE` is hukilau's `restore_from_stdin` (commit `c5743d2`, checked there against a
throwaway PostgreSQL 16 container). Keep its `pg_restore --no-owner` and
`psql --file=-`. `read -r answer || true` keeps a final `y` sent without a newline;
bash leaves `answer` empty at end of input.

### 8. `scripts/remote-deploy.sh` and `package.json`

Replace the whole of `remote-deploy.sh`:

```bash
#!/usr/bin/env bash
# SSH into the server and run scripts/deploy.sh there. Runs on a laptop.
# Usage:
#   npm run deploy                          # production, host from DEPLOY_HOST
#   npm run deploy:staging                  # staging, host from DEPLOY_HOST
#   npm run deploy -- ubuntu@1.2.3.4        # explicit host (any ssh target or alias)
#   bash scripts/remote-deploy.sh [--environment <name>] [<host>]
#
# Production's clone on the server is ~/<APP_NAME>, where APP_NAME is read from the
# local .env (falling back to .env.example), matching what provision.sh wrote. Any other
# environment's clone is ~/<APP_NAME>-<environment>, whose own .env sets that APP_NAME
# (.env.staging.example). deploy.sh refuses a clone whose .env deploys another
# environment.
set -euo pipefail

usage() {
  echo 'usage: bash scripts/remote-deploy.sh [--environment <name>] [<host>]' >&2
  exit 1
}

ENVIRONMENT=production
TARGET=''
while [ $# -gt 0 ]; do
  case "$1" in
    --environment) [ $# -ge 2 ] || usage; ENVIRONMENT=$2; shift 2 ;;
    --environment=*) ENVIRONMENT=${1#--environment=}; shift ;;
    -*) usage ;;
    *) [ -z "$TARGET" ] || usage; TARGET=$1; shift ;;
  esac
done
# The name becomes part of a path and of the remote command line. Bash 3.2 matches a
# range such as a-z by the locale's collation, so the letters are spelled out.
case "$ENVIRONMENT" in
  '' | *[!abcdefghijklmnopqrstuvwxyz0123456789-]*) usage ;;
esac
TARGET="${TARGET:-${DEPLOY_HOST:-}}"
if [ -z "$TARGET" ]; then
  echo 'ERROR: set DEPLOY_HOST or pass a host.' >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"

get() { grep -E "^$1=" "$2" 2>/dev/null | tail -1 | cut -d= -f2- || true; }

APP_NAME="$(get APP_NAME "$REPO_DIR/.env")"
[ -n "$APP_NAME" ] || APP_NAME="$(get APP_NAME "$REPO_DIR/.env.example")"
if [ -z "$APP_NAME" ]; then
  echo "ERROR: APP_NAME is not set in $REPO_DIR/.env or .env.example."
  exit 1
fi
CLONE="$APP_NAME"
[ "$ENVIRONMENT" = production ] || CLONE="$APP_NAME-$ENVIRONMENT"

echo "==> Deploying $ENVIRONMENT ($CLONE) to $TARGET..."
# CLONE and ENVIRONMENT are resolved here on purpose; the quoted ~ is left for the
# remote shell.
# shellcheck disable=SC2029
ssh "$TARGET" "bash ~/$CLONE/scripts/deploy.sh --environment $ENVIRONMENT"
```

The `package.json` change is in section 3.

### 9. `scripts/worktree-setup.sh`

Replace lines 29-42 with the block below. Header line 12, "main/ keeps offset 0",
stays as it is.

```sh
# Fetch so new branches fork from the current integration branch, and a freshly pushed
# remote branch is detected rather than recreated locally and divergent.
git fetch origin

# Create the worktree: track an existing origin branch, else branch off origin/staging,
# the default branch, where it exists, else origin/main. A bare clone made without a
# fetch refspec has no origin/* refs; fall back to the local main branch in that case.
if git show-ref --verify --quiet "refs/remotes/origin/$branch"; then
  git worktree add "$slug" "$branch"
elif git show-ref --verify --quiet refs/remotes/origin/staging; then
  git worktree add "$slug" -b "$branch" origin/staging
elif git show-ref --verify --quiet refs/remotes/origin/main; then
  git worktree add "$slug" -b "$branch" origin/main
else
  git worktree add "$slug" -b "$branch" main
fi
```

### 10. `scripts/provision.sh` and `scripts/install-backup.sh`

**`provision.sh`**:

- Line 5 becomes `#   git clone --branch main <repo-url> ~/<app-name> && cd ~/<app-name>`.
  Add a line after it: `staging` is the default branch, so production names `main`.
- In the heredoc, after the Identity block (line 83), add:

```text

# --- Environment and branch (scripts/deploy.sh) ---------------------------------
# Production serves the main branch; deploy.sh refuses a clone on any other branch.
APP_ENVIRONMENT=production
DEPLOY_BRANCH=main
```

**`install-backup.sh`**: after the `APP_NAME` check (line 22), add the guard below. The
script writes a single host-wide `/root/.config/rclone/rclone.conf`, so a run from
staging's clone would replace production's remote.

```bash
# The rclone remote is host-wide, so a run from another environment's clone would
# replace production's remote with that clone's settings.
ENVIRONMENT="$(get APP_ENVIRONMENT)"
if [ "${ENVIRONMENT:-production}" != production ]; then
  echo "ERROR: $REPO_DIR/.env deploys $ENVIRONMENT; backups belong to production." >&2
  echo "       Run install-backup.sh from production's clone." >&2
  exit 1
fi
```

### 11. Shell tests

Each new test follows `ai/conventions.md`, "Shell Scripts". It copies the script into
`mktemp -d`, rewrites host paths with `sed`, and checks no `/etc/` survives after
stripping `$TEST_DIR`. Stubs come first on `PATH` and must pass a shadow check. Each
stub logs its call to `commands`. Checks use inline `assert_contains`,
`refute_contains`, `assert_line`, and `expect_calls`, copied from `test-deploy.sh`. The
tests must run under Bash 3.2 and exit 77 when a needed tool is missing.

**`test-deploy.sh`** (extend):

- **git stub** (lines 86-91): add a case. `$flags/detached` simulates a detached HEAD,
  and `$flags/branch` holds the checked-out branch.

    ```bash
      'symbolic-ref --quiet --short HEAD')
        [ ! -f "$flags/detached" ] || exit 1
        if [ -f "$flags/branch" ]; then cat "$flags/branch"; else echo main; fi
        ;;
    ```

- **Helpers**: `run_deploy_script` forwards its arguments:
  `(umask 077; bash "$TEST_DIR/repo/scripts/deploy.sh" "$@") > "$OUTPUT" 2>&1`.
  `run_deploy` forwards `"$@"`. `expect_failure DESCRIPTION [ARG...]` stores the
  description, shifts it off, and forwards the rest.
- **Existing call lists**: in cases 1 and 3 (lines 217-237 and 269-285), insert
  `"git symbolic-ref --quiet --short HEAD"` right before `"git rev-parse HEAD"`.
- **Case 2**: also check that a production site carries no basic auth:
  `refute_contains '^[^#]*auth_basic' "$NGINX_DIR/sites-available/$APP"`.
- **Staging example keys**: next to the other fixture checks (lines 114-118), check that
  every key in `.env.staging.example` appears in `.env.example`. Use the
  `generated-keys` loop from `test-provision.sh:156-164`. Also check
  `^APP_ENVIRONMENT=staging$` and `^DEPLOY_BRANCH=staging$` in `.env.staging.example`.
- **New cases**, appended:
    1. **A staging deploy**.
        - Setup:

            ```bash
            start_test_case APP_ENVIRONMENT=staging DEPLOY_BRANCH=staging \
              "STAGING_HTPASSWD=$TEST_DIR/staging.htpasswd"
            touch "$TEST_DIR/staging.htpasswd"
            echo staging > "$FLAGS/branch"
            add_data_volumes
            run_deploy --environment staging
            ```

        - `expect_calls`: case 1's list without the three database-backup lines
          (`up -d db`, `pg_isready`, `backup.sh ...`) and the two closing systemd lines
          (`daemon-reload`, `enable --now`).
        - `[ -z "$(find "$SYSTEMD_DIR" -type f)" ]`: no units and no drop-in.
        - `assert_line` on the site file for this exact line, its four leading spaces
          included:

            ```text
                auth_basic "$APP"; auth_basic_user_file $TEST_DIR/staging.htpasswd;
            ```

        - The output says `staging deploys take no pre-migration backup`.
        - No renewal hook is installed:
          `[ ! -e "$LETSENCRYPT_DIR/renewal-hooks/deploy/reload-nginx.sh" ]`.
    2. **The environment must match**.
        - A production `.env` with `expect_failure '...' --environment staging`. The
          output matches `asked to deploy staging, but .* deploys`, and
          `assert_no_commands`.
        - The reverse: a staging `.env` with no flag. The output matches
          `asked to deploy production`, and `assert_no_commands`.
    3. **The branch must match**.
        - Production `.env`, `add_data_volumes`, `echo staging > "$FLAGS/branch"`. The
          output says `is on staging, but its .env deploys main`. The last command is
          `git symbolic-ref --quiet --short HEAD`. Refute `^git pull` and
          `^docker compose`.
        - Repeat with `touch "$FLAGS/detached"`: the output says
          `is on a detached HEAD`.
        - Start afresh with
          `start_test_case APP_ENVIRONMENT=staging DEPLOY_BRANCH=staging` and
          `add_data_volumes`. Write no branch flag, so the stub answers `main`. Then
          pass `--environment staging`, or the environment guard fires first. The
          output says `is on main, but its .env deploys staging`.
    4. **A missing htpasswd file**:
       `start_test_case "STAGING_HTPASSWD=$TEST_DIR/missing.htpasswd"`. The output says
       `STAGING_HTPASSWD names .* which does not exist`, and `assert_no_commands`.
    5. **Usage errors**: `--bogus`, a bare `--environment`, and `--environment=` each
       print `usage: bash scripts/deploy.sh`, with `assert_no_commands`.

**`test-nginx-site.sh`** (extend):

- **Render loop** (lines 37-50): render `alpha beta gamma`, and add
  `-e "s|__BASIC_AUTH__|$basic_auth|g"` to the `sed`. At the top of the loop:

    ```bash
    basic_auth=''
    if [ "$app" = gamma ]; then
      basic_auth="auth_basic \"$app\";"
      basic_auth="$basic_auth auth_basic_user_file /etc/nginx/conf.d/$app.htpasswd;"
    fi
    ```

- **Password file**: after the loop, write
  `printf 'tester:{PLAIN}secret\n' > "$TEST_DIR/conf.d/gamma.htpasswd"`. Then run
  `chmod 755 "$TEST_DIR/conf.d"` and `chmod 644` on the file. nginx's worker (uid 101)
  opens it on every request through the read-only mount, unlike the files the root
  master reads at startup, so a strict umask would turn the 401 into a 500. nginx's
  built-in `{PLAIN}` scheme needs no `htpasswd` tool, and `conf.d/*.conf` never
  includes the file.
- **Comment**: change the loop's comment to "Three apps on one host ... gamma behind
  basic auth".
- **New checks**, after the beta checks (before line 148):
    - `fetch gamma /` answers 401. `assert_security_headers` passes, and so does
      `assert_header WWW-Authenticate 'Basic realm="gamma"'`.
    - `fetch gamma /api/health` answers 401, because the API sits behind the password
      too.
    - `fetch gamma / -u tester:secret` and `fetch gamma /api/health -u tester:secret`
      both answer 200.
    - alpha already answers 200 without credentials.

**`test-provision.sh`** (extend): after line 150, add
`assert_contains '^APP_ENVIRONMENT=production$' "$ENV_FILE"` and
`assert_contains '^DEPLOY_BRANCH=main$' "$ENV_FILE"`. The key loop at lines 156-164
then requires both keys in `.env.example`, which section 3 adds.

**`test-compose-config.sh`** (extend):

- Line 24: add `APP_ENVIRONMENT` to the `unset` list.
- After the `prod-workers` render (lines 36-39), render `prod-staging.json` the same
  way, with `export APP_ENVIRONMENT=staging`.
- Add these checks:

```bash
check prod '.services.backend.environment.APP_ENVIRONMENT == ""' \
  'a blank APP_ENVIRONMENT, which the backend reads as production'
check prod-staging '.services.backend.environment.APP_ENVIRONMENT == "staging"' \
  'APP_ENVIRONMENT passed through to the backend'
```

**`test-copy-production.sh`** (new):

- **Layout**: `$TEST_DIR/staging/scripts/copy-production.sh` is a copy, with
  `/etc/nginx` rewritten to `$TEST_DIR/nginx`. After stripping `$TEST_DIR`, no
  `/etc/` may remain.
- **`install_site LINE`** renders the real `scripts/nginx-ssl.conf.template` into
  `$TEST_DIR/nginx/sites-available/app-staging`. It replaces only `__BASIC_AUTH__`,
  with LINE, as `deploy.sh` would; the guard reads nothing else.
- **`start_test_case [STAGING-LINE...]`** rewrites both `.env` files for every case,
  so no case inherits another's changes.
    - Production's `.env` holds `APP_ENVIRONMENT=production`,
      `COMPOSE_PROJECT_NAME=app`, `POSTGRES_USER=app`, and `POSTGRES_DB=app`. A case
      that needs another production value appends it afterwards; `get` reads the
      last matching line.
    - Staging's `.env` holds `APP_ENVIRONMENT=staging`,
      `COMPOSE_PROJECT_NAME=app-staging`, `APP_NAME=app-staging`,
      `PRODUCTION_DIR=$TEST_DIR/production`, `POSTGRES_USER=app`, `POSTGRES_DB=app`,
      `BACKEND_PORT=5001`, then `"$@"`.
    - It resets `flags` and `commands`, touches the volume flags for
      `app_uploads_data` and `app-staging_uploads_data`, and runs
      `install_site 'auth_basic "app-staging"; auth_basic_user_file /x;'`.
- **Stub**: one `mock-command` behind `docker`, `curl`, and `sleep`. The restore
  command carries a multi-line script, so the stub logs each call on one line:
  `printf '%s\n' "$(printf '%s' "$name $*" | tr '\n' ' ')" >> "$TEST_DIR/commands"`.

    ```bash
    docker)
      case "$*" in
        'volume inspect '*) [ -f "$flags/volume-$3" ] || exit 1 ;;
        *' exec -T db pg_dump '*)
          [ ! -f "$flags/dump-fails" ] || exit 1
          echo 'PGDMP standing in for production' ;;
        *' exec -T db sh -c '*)
          cat > "$TEST_DIR/restored"   # drain stdin so the writer never gets SIGPIPE
          [ ! -f "$flags/restore-fails" ] || exit 1 ;;
        'run --rm '*) [ ! -f "$flags/uploads-fail" ] || exit 1 ;;
        'compose '*) ;;
        *) echo "Unexpected docker call: $*" >&2; exit 1 ;;
      esac
      ;;
    curl) [ ! -f "$flags/backend-down" ] || exit 7 ;;
    sleep) ;;
    ```

- **Order**: the dump and the restore are the two ends of one pipe, so their order in
  `commands` is not fixed. Add `assert_before PATTERN-A PATTERN-B`, which compares the
  line numbers of the first `grep -nF` match of each fixed string. Never `diff` the
  whole log here.
- **Cases**:
    1. **`--yes` copies**.
        - Exit 0, and the output says `Staging now holds a copy of production.`
        - `assert_line` for each exact call, built the way `test-deploy.sh:108-111`
          builds `COMPOSE`, besides both `volume inspect` calls:

            ```bash
            STAGING_COMPOSE='docker compose -f docker-compose.yml'
            STAGING_COMPOSE+=' -f docker/docker-compose.prod.yml --env-file .env'
            PRODUCTION="$TEST_DIR/production"
            PRODUCTION_COMPOSE="docker compose -f $PRODUCTION/docker-compose.yml"
            PRODUCTION_COMPOSE+=" -f $PRODUCTION/docker/docker-compose.prod.yml"
            PRODUCTION_COMPOSE+=" --env-file $PRODUCTION/.env"
            COPY='docker run --rm -v app_uploads_data:/from:ro'
            COPY+=' -v app-staging_uploads_data:/to alpine sh -c'
            COPY+=' find /to -mindepth 1 -delete && cp -a /from/. /to/'
            assert_line "$COMMANDS" "$STAGING_COMPOSE stop backend"
            assert_line "$COMMANDS" \
              "$PRODUCTION_COMPOSE exec -T db pg_dump -U app -d app -Fc"
            assert_line "$COMMANDS" "$COPY"
            assert_line "$COMMANDS" "$STAGING_COMPOSE start backend"
            assert_line "$COMMANDS" 'curl -fsS http://127.0.0.1:5001/api/health'
            ```

        - The restore line contains `exec -T db sh -c`,
          `pg_restore --no-owner --file=`,
          `DROP SCHEMA public CASCADE; CREATE SCHEMA public;`,
          `--single-transaction`, `--file=-`, and `ON_ERROR_STOP=1`.
        - `$TEST_DIR/restored` is exactly `PGDMP standing in for production`, which
          shows the pipe joined the two calls.
        - Order: `stop backend` comes before both `pg_dump` and `sh -c`; both come
          before `docker run`; `docker run` comes before `start backend`; and
          `start backend` comes before `curl`.
    2. **It asks first**.
        - stdin `n` exits 1 with `Nothing changed.`, and no `stop backend` is
          logged.
        - stdin `/dev/null` does the same.
        - stdin `y` reaches `stop backend` and exits 0.
    3. **Refuses outside staging**: `APP_ENVIRONMENT=` (blank), `production`, and `qa`.
       Each exits 1 with `only staging copies production`, and no command runs.
    4. **Refuses a bad `PRODUCTION_DIR`**: an empty one exits 1 with
       `PRODUCTION_DIR is empty`, and a directory without `.env` with `no .env in`. No
       command runs.
    5. **Refuses when "production" is not production**: after `start_test_case`,
       append `APP_ENVIRONMENT=staging` to production's `.env`. It exits 1 with
       `deploys staging, not production`, and no command runs.
    6. **Refuses matching or blank project names**: `COMPOSE_PROJECT_NAME=app`, then
       `COMPOSE_PROJECT_NAME=`. Each exits 1 with
       `need different COMPOSE_PROJECT_NAME values`, and no command runs.
    7. **Refuses different database names**: `POSTGRES_DB=other`, then
       `POSTGRES_USER=other`. Each exits 1 with `must match production's`, and no
       command runs.
    8. **Refuses a missing uploads volume**: remove staging's volume flag. It exits 1
       with `volume app-staging_uploads_data does not exist`, and no `stop backend` is
       logged.
    9. **A failed dump**, then **a failed restore**: each exits 1 with
       `staging's database is unchanged`. No `docker run` is logged, and the last
       command is staging's `start backend`.
    10. **Failed uploads**: exits 1 with `staging holds production's database`. The last
        command is `start backend`.
    11. **Backend never healthy**: exits 1, with 60 `sleep 2` calls and
        `logs --tail 50 backend`.
    12. **Usage**: `--bogus` exits 1 with `usage:`, and no command runs.
    13. **No basic auth**: `install_site ''`, the real template with its line left
        blank, then a missing site file. Each exits 1 with `asks for no password`, and
        no command runs.

**`test-remote-deploy.sh`** (new):

- **Setup**: copy the script to `$TEST_DIR/repo/scripts/`. Write `.env` with
  `APP_NAME=myapp` and `.env.example` with `APP_NAME=from-example`. Stub `ssh` to log
  its arguments. Run `unset DEPLOY_HOST` first.
- **Cases**:
    1. `DEPLOY_HOST=root@example.com` and no arguments logs exactly the first line
       below.
    2. `--environment staging` logs exactly the second:

        ```text
        ssh root@example.com bash ~/myapp/scripts/deploy.sh --environment production
        ssh root@example.com bash ~/myapp-staging/scripts/deploy.sh --environment staging
        ```

    3. `--environment=staging other-host` and `other-host --environment staging` both
       target `other-host` and `~/myapp-staging`.
    4. No host and no `DEPLOY_HOST`: exits 1 with `set DEPLOY_HOST or pass a host`. No
       `ssh` runs. The explicit check replaces `${DEPLOY_HOST:?}`, which exits 127
       under Bash 3.2.
    5. A `.env` without `APP_NAME` falls back to `~/from-example`. With neither file
       setting it, it exits 1 with `APP_NAME is not set`, and no `ssh` runs.
    6. `--environment Staging`, `--environment 'a;b'`, `--bogus`, and two hosts each
       print the usage line, and no `ssh` runs.

**`test-certbot-setup.sh`** (new):

- **Rewrites**: `/etc/letsencrypt` becomes `$TEST_DIR/letsencrypt`, and `/etc/nginx`
  becomes `$TEST_DIR/nginx`.
- **Stubs**:
    - `sudo` is its own stub script, not a link to the logging `mock-command`, so the
      call lists below hold only the commands it runs. It runs its arguments. For
      `sed -i EXPR FILE`, it runs `sed EXPR FILE > FILE.tmp && mv FILE.tmp FILE`
      instead, because BSD `sed -i` needs a suffix. It must pass the shadow check like
      the other stubs.
    - `systemctl` logs, and answers `is-active --quiet X` from `$flags/active-X`;
      `stop` and `start` remove or touch that flag.
    - `certbot` logs. It fails while `$flags/certbot-fails` exists. Otherwise it writes
      `authenticator = standalone` or `authenticator = nginx`, following its flag, to
      `$TEST_DIR/letsencrypt/renewal/<domain>.conf`.
    - `dig` prints `203.0.113.10`. `curl` prints the same, or `198.51.100.1` while
      `$flags/other-ip` exists.
    - `.env` holds `DOMAIN=example.com` and `CERTBOT_EMAIL=you@example.com`.
- **Cases**:
    1. **Bare host**: nginx active, `sites-enabled` empty.
        - The exact calls:

            ```bash
            STANDALONE='certbot certonly --standalone -d example.com'
            STANDALONE+=' --non-interactive --agree-tos -m you@example.com'
            expect_calls 'dig +short example.com' 'curl -s https://api.ipify.org' \
              'systemctl is-active --quiet nginx' \
              'systemctl is-active --quiet nginx' 'systemctl stop nginx' \
              'systemctl is-active --quiet apache2' "$STANDALONE" \
              'systemctl start nginx'
            ```

        - The renewal conf reads `authenticator = nginx`, and the output says
          `(verified)`.
    2. **nginx serving a site**: `sites-enabled/myapp` exists.
        - The calls are `dig`, `curl`, one `is-active nginx`, and
          `certbot certonly --nginx -d example.com ...`.
        - There is no `stop` or `start`.
        - The output says `already serves a site`.
    3. **nginx inactive, with a site**: takes the standalone path, but nothing is
       stopped or started. Exit 0, which proves the restore loop survives an empty
       array under bash 3.2.
    4. **Standalone certbot fails**: exits non-zero, and the last command is
       `systemctl start nginx`.
    5. **`--nginx` certbot fails**: exits non-zero, with no `stop` and no `start`.
    6. **DNS mismatch**: exits 1 with `resolves to`, and neither `certbot` nor
       `systemctl` runs.
    7. **No email**: `CERTBOT_EMAIL=` and no `--email` exits 1 with
       `no registration email`.

**`test-worktree-setup.sh`** (new). It uses real git, and exits 77 without git.

- **Isolation**: `export GIT_CONFIG_GLOBAL="$TEST_DIR/gitconfig" GIT_CONFIG_NOSYSTEM=1`,
  with a config holding `user.name`, `user.email`, and `commit.gpgsign = false`.
- **Seed repository**: `git init -q -b main seed`, which commits a copy of the real
  `.env.example`. It then makes an empty commit on a new `staging`, and another on
  `issue-2-existing`, branched from `main`.
- **Origins**: `origin.git` is `git clone --bare seed`.
  `origin-main.git` is `git clone --bare --single-branch --branch main seed`.
- **Containers**: `container-a` and `container-b` are each `mkdir`, then
  `git clone --bare <origin> <container>/.git`, then
  `git -C <container> config remote.origin.fetch '+refs/heads/*:refs/remotes/origin/*'`,
  matching README, Worktrees.
- **Stubs**:
    - `python3` accepts only `-m venv .venv`. It creates `.venv/bin` and symlinks
      `.venv/bin/pip` to the mock, which logs `pip ...`.
    - `npm` logs.
    - Pass explicit offsets, so `lsof` is never called.
- **Cases**: run `(cd container-x && sh "$TEST_DIR/worktree-setup.sh" <branch> <offset>)`.
    1. `container-a`, `issue-1-new 3`.
        - `rev-parse HEAD` in the worktree equals seed's `staging`, and the branch is
          `issue-1-new`.
        - `.env` has `COMPOSE_PROJECT_NAME=container-a-issue-1-new`, `DB_PORT=5435`,
          `BACKEND_PORT=5003`, `FRONTEND_PORT=5177`, and
          `PUBLIC_BASE_URL=http://localhost:5177`.
        - `commands` has `python3 -m venv .venv`, `pip install -r requirements-dev.txt`,
          and `npm install`.
    2. `container-a`, `issue-2-existing 4`: HEAD equals seed's `issue-2-existing`.
    3. `container-b`, `issue-1-new 3`: HEAD equals seed's `main`.

**`test-install-backup.sh`** (extend): add a case with `APP_ENVIRONMENT=staging`
in `.env`. It uses the existing exit-1 helper (lines 95-100), expects the output
`backups belong to production`, and calls `expect_no_calls`. `rclone.conf` must not
exist.

### 12. Documentation

Keep every line to 90 characters. Use 4-space nested lists, and indent code blocks
inside numbered steps by 4 spaces, as `ai/backups.md` does. `npm run lint:md` must pass.

**`ai/staging.md`** (new). Add it to `AGENTS.md` (after line 10) and
`.claude/CLAUDE.md` (`@../ai/staging.md` after line 8). Sections:

- **`# Staging` / `## Overview`**: what the section 3 `.env.staging.example` sets apart
  (domain, names, ports, secrets, database, uploads, session cookie), and what it
  shares (`POSTGRES_USER` and `POSTGRES_DB`). It covers the `STAGING` badge and the tab
  prefix on every page, the sign-in page included, and that `/api/health` reports the
  environment. It also covers what a staging deploy does not install, and why:
  pre-migration dumps, backups, and the drill, because the data is a disposable copy;
  and the renewal hook and certificate monitoring, because production's hook and units
  cover every certificate on the host and `certbot.timer` renews both. A staging
  deploy changes only its own nginx site.
- **Shared host state**, a short paragraph in the Overview. Both sites define nginx's
  `$auth_post_client_address` map. nginx keeps the definition it reads last, and it
  reads sites in alphabetical order, so staging's wins. A change to that map therefore
  reaches production's sign-in throttling at the next staging deploy, before the
  release. `ai/auth.md` already says every site must define it the same way.
- **`## Setting up staging`**, as numbered steps, all as root on the server once
  production runs there:
    1. A DNS record for the staging host name.
    2. `git clone --branch staging <your-repo-url> ~/my-app-staging`, then
       `cp .env.staging.example .env && chmod 600 .env`.
    3. Fill in `.env`: fresh secrets, and `POSTGRES_PASSWORD` repeated in
       `DATABASE_URL`.
    4. The password file:

        ```bash
        printf 'tester:%s\n' "$(openssl passwd -6)" > /etc/nginx/my-app-staging.htpasswd
        chown root:www-data /etc/nginx/my-app-staging.htpasswd
        chmod 640 /etc/nginx/my-app-staging.htpasswd
        ```

    5. `bash scripts/certbot-setup.sh`. Because production's nginx already serves, it
       uses `--nginx`, and production stays up.
    6. `DEPLOY_HOST=root@example.com npm run deploy:staging` from a laptop, or
       `bash scripts/deploy.sh --environment staging` on the server.
- **`## Deploying`**: what `npm run deploy` and `npm run deploy:staging` run, and the
  two `deploy.sh` refusals (environment, branch) with the reason for each.
- **`## Copying production into staging`**:
    - When to do it: before releasing a migration that rewrites existing rows.
    - The command, `bash scripts/copy-production.sh`, with `--yes`.
    - Every refusal.
    - What happens, in order: the backend stops, a one-transaction restore, the
      uploads, the restart, and migrations run on the copy.
    - Testers then sign in with production passwords.
    - The copy holds every account's email and password hash, so staging must stay
      behind its password. The script refuses until staging's installed nginx site
      asks for one; set `STAGING_HTPASSWD` and deploy staging first.
- **`## Branches and releases`**:
    - The default branch, and that issues close when their PR merges into `staging`.
    - The release commands:

        ```bash
        gh pr create --base main --head staging --title "Release $(date +%F)" \
          --body "Promotes staging to production."
        gh pr merge <number> --merge
        git fetch origin
        git diff --stat origin/staging origin/main   # must print nothing
        npm run deploy
        ```

    - The hotfix commands, adapted from hukilau's `ai/lan.md` "Releases": branch from
      `origin/main`, open the PR against `main`, merge it, and deploy production. Then
      bring the fix back through `sync-main-into-staging`, cut from `origin/main`,
      merged into `staging` with `--merge`. Never use `main` itself as a PR's head,
      because GitHub can delete a merged head branch, and this repository does.
- **`## Repository settings`**:
    - The one-time switch: cut `staging` from `main`, make it the default, and run
      `git remote set-head origin --auto` in each clone. Local fallow audits fall back
      to `origin/HEAD` for their base.
    - The two rulesets from section 13. `main` takes changes only through PRs merged
      with a merge commit, and neither branch can be deleted or force-pushed.
      Rulesets are free on public repositories; a private one needs GitHub Pro or
      Team, and without them the rules are conventions.
    - For a project made from this template, GitHub copies only the default branch
      unless "Include all branches" is ticked. If `main` is missing, create it from
      `staging`, and keep `staging` as the default.

**`ai/conventions.md`**: replace the review-base bullet in "## Git" (lines 226-227) with
hukilau's rules, adapted:

```markdown
- `staging` is the default branch. Feature branches fork from `origin/staging`, PRs
  target it, and review diffs use `origin/staging...HEAD`.
- A release is a PR from `staging` into `main`, merged with "Create a merge commit".
  Never squash or rebase it: both rewrite staging's commits, so `main` would stop
  containing them and every later release would conflict. After the merge,
  `git diff origin/staging origin/main` must print nothing.
- A hotfix branches from `origin/main` and targets `main`. Bring it back into `staging`
  through a throwaway branch cut from `origin/main` (`ai/staging.md`, "Branches and
  releases"), never with `main` as a PR's head, since merged head branches are deleted.
- Issues close when their PR merges into `staging`, before they reach production:
  GitHub honors closing keywords only on the default branch.
```

**`README.md`**:

- **Line 6**: "deploy a single server" becomes "deploy a single server, with an
  optional staging stack beside production".
- **Starting a new project** (lines 34-36): the app bar bullet becomes "`APP_TITLE` in
  `src_front/src/appTitle.ts`, which the app bar and the tab title use, and the tests
  that expect it, ...", keeping the two test paths. After the list, add a paragraph:
  GitHub copies only the default branch, `staging`, unless all branches are included.
  Create `main` from it (`git push origin origin/staging:refs/heads/main`), keep
  `staging` as the default, and see `ai/staging.md`. Also add a checklist bullet:
  `APP_NAME`, `COMPOSE_PROJECT_NAME`, `PRODUCTION_DIR`, `STAGING_HTPASSWD`, and
  `WEBAUTHN_RP_NAME` in `.env.staging.example`, which carry the template's name.
- **Worktrees** (line 150): `worktree-setup.sh` creates the worktree "on a new branch
  from `origin/staging`, or `origin/main` where there is no `staging`".
- **Scripts table** (after line 193): add this row, then let Prettier align the table:

    ```text
    | `npm run deploy:staging` | Deploy the staging clone (`ai/staging.md`)      |
    ```

- **Agent instructions** (lines 252-254): add `ai/staging.md` to the operations
  runbooks.
- **New `## Branches and releases`** before `## Deployment` (line 281): `staging` is
  the default branch; feature branches fork from it and PRs merge into it; a release
  is a merge-commit PR into `main`, after which production deploys `main`.
  `ai/conventions.md` holds the rules, and `ai/staging.md` the commands and the
  staging server.
- **Deployment**:
    - Line 291 becomes `git clone --branch main <your-repo-url> ~/my-app && cd ~/my-app`.
    - Line 298: add that `npm run deploy:staging` deploys the staging clone.
    - Lines 299-303: `deploy.sh` first refuses a clone on the wrong branch or
      environment. A staging deploy skips the backup, the renewal hook, and the
      timers. One sentence points to `ai/staging.md` for running staging beside
      production.

**`ai/project.md`**:

- **Project Structure**: the `scripts/` bullet says "deployment (production and
  staging)".
- **Commands** (line 77): after `npm run deploy`, add
  `npm run deploy:staging` - "deploy the staging clone the same way (`ai/staging.md`)".
- **Database** (lines 103-104): "it takes a database backup" becomes "it takes a
  database backup in production".
- **Environment** (lines 114-128):
    - Add: `.env.staging.example` is a whole staging `.env`.
    - Add: `APP_ENVIRONMENT` names the deployment, production when blank. `/api/health`
      reports it, the frontend badges every page outside production, and any other
      environment names its own session cookie. `DEPLOY_BRANCH` is the branch a server
      clone must be on.
    - The monkeypatch sentence adds: "`conftest.py` clears `APP_ENVIRONMENT` for every
      test".
- **Worktrees** (lines 132-137): new branches fork from `origin/staging`.

**`ai/domain.md`**, Test Fixtures: add a bullet saying an autouse fixture clears
`APP_ENVIRONMENT`, so a developer's `.env` cannot rename the session cookie.

**`ai/auth.md`**, "## Configuration": add a bullet. `APP_ENVIRONMENT`
(`ai/staging.md`) gives every environment but production the session cookie
`<environment>_session`, so a sign-in on staging never replaces production's.

**`ai/backups.md`**:

- **Overview** (line 11): "Every deploy" becomes "Every production deploy". Add a
  sentence: staging (`ai/staging.md`) has none of this, because its data is a copy of
  production's.
- **Setup** (lines 90-91): "on every deploy" becomes "on every production deploy".
  In step 3, add that `install-backup.sh` refuses a clone that deploys anything but
  production, because the rclone remote is host-wide.
- **Pre-migration dumps** (line 115): the paragraph opens with "A production deploy
  runs" and adds "A staging deploy takes none."
- **Orphaned-volume cleanup**: "NEVER touch `<COMPOSE_PROJECT_NAME>_*`" adds
  "production's or staging's".

**`ai/tls.md`**:

- **Overview** (lines 7-10): a second certificate on the host, staging's, also comes
  from `certbot-setup.sh`, through the running nginx.
- **Authenticators**: after line 16, add a paragraph. When nginx already serves a site,
  `certbot-setup.sh` uses `--nginx` and stops nothing, so issuing staging's certificate
  leaves production up.
- **Reload after renewal** (lines 46-48): the hook is "installed by a production
  deploy".
- **Monitoring** (line 68): "A production deploy installs all of this, the renewal
  hook included; a staging deploy installs none of it, since production's hook and
  units cover every certificate on the host."
- **Security headers**: one clause saying a basic-auth 401 carries them too.

**`tools.md`**: anchor each edit on the bullet's name. The line numbers are as of
`98dc33b`.

- **Docker daemon, curl, and openssl** (228-231): "rendered for two apps" becomes
  "rendered for three apps, one behind basic auth".
- **`alpine`** (266-269): add that `scripts/copy-production.sh` uses it to copy
  production's uploads volume into staging's.
- **Servers and operations** intro: `scripts/deploy.sh` installs the nginx site, and,
  in production only, the renewal hook and the units.
- **Host nginx** (297-301): add basic auth when `STAGING_HTPASSWD` is set.
- **Certbot and Let's Encrypt** (302-306): the first issuance on a bare host is
  standalone, and a later one goes through the running nginx.
- **systemd** (307-313): "A production deploy installs them all".
- **pg_dump and pg_restore** (319-323): add a sentence on `copy-production.sh`.
- **OpenSSL** (324-325): add that `openssl passwd -6` hashes staging's password file.
- **git** (335-336): every deploy first checks the clone is on `DEPLOY_BRANCH`.
- **SSH** (341-342): name `npm run deploy:staging` too.

### 13. After the merge (Chuck runs or approves; outward-facing)

```bash
git fetch origin
git push origin origin/main:refs/heads/staging      # cut staging from the merge
gh repo edit chivalry/flask-react-template --default-branch staging
git remote set-head origin --auto                   # origin/HEAD -> origin/staging
git switch staging && git branch -u origin/staging
```

**Rulesets**, approved (the repository is public, so they are free):

- `main`: `deletion`, `non_fast_forward`, and `pull_request` with
  `required_approving_review_count: 0` and `allowed_merge_methods: ["merge"]`.
- `staging`: `deletion` and `non_fast_forward`.

Each one is `gh api -X POST repos/chivalry/flask-react-template/rulesets --input <json>`.
If the API rejects `allowed_merge_methods`, set "Allowed merge methods: Merge" in
Settings → Rules instead.

**`~/.ai/standards/git.md`**, approved (outside the repository, done in the
implementation session): replace each hard-coded `origin/main` (lines 29, 38-40, 68,
85) with `origin/$base`, where
`base=$(gh repo view --json defaultBranchRef --jq .defaultBranchRef.name)`, as
`review-pr.md:27` already does.

Then verify the acceptance criteria on the server: section "Verification", step 6.

## Parallelism

Implementer model for every group: Sonnet 5.5 (per #27).

- **Can be done in parallel**:
    - **Group A, backend**: section 1.
    - **Group B, frontend**: section 2.
    - **Group C, deploy path**: the compose file, `.env.example`,
      `.env.staging.example`, and `package.json` (section 3); `deploy.sh` (section 4);
      the nginx template (section 5); `provision.sh` and `install-backup.sh`
      (section 10); and their tests: `test-deploy.sh`, `test-nginx-site.sh`,
      `test-provision.sh`, `test-compose-config.sh`, and `test-install-backup.sh`.
      These share the placeholder name, the `.env` keys, and the key-coverage checks,
      so one agent owns them.
    - **Group D, standalone scripts**: `copy-production.sh`, `remote-deploy.sh`,
      `certbot-setup.sh`, and `worktree-setup.sh` (sections 6-9), with their four new
      tests. Group D reads `.env.staging.example` but does not write it.
- **Must be sequential**:
    - **Group E, docs** (section 12) comes after A-D, because the docs describe their
      final messages and behavior.
    - Then the full checks.
    - The post-merge steps (section 13) wait for the merge.

## No other changes needed

- `.github/workflows/ci.yml`: already runs on `'**'` for pushes and PRs, and its fallow
  base falls back to `github.event.repository.default_branch`.
- `docker-compose.yml` (development): the badge needs no development wiring, and
  `APP_ENVIRONMENT` stays blank, which means production.
- `docker/entrypoint.sh`, `backup.sh`, `restore-drill.sh`, `scripts/systemd/*`,
  `cert-check.sh` (which checks every certificate on the host), and
  `letsencrypt-deploy-hook.sh` (one host-wide file).
- `src_front/index.html` keeps its `<title>`; `appTitle.ts` and the README checklist
  pair them.
- The home-directory skills `/create-pr`, `/review-pr`, `/plan-pr`, and `/plan-issue`
  already read `defaultBranchRef`, and `/new-issue` prefers `staging`.
- PR #9 merged on 2026-10-24.

## Verification

1. While editing, run targeted tests only:

    ```bash
    .venv/bin/python -m pytest src_back/tests/test_health.py \
      src_back/tests/test_app.py --no-cov
    npx vitest run src_front/src/test/components/layout/EnvironmentBadge.test.tsx ...
    bash scripts/tests/test-<name>.sh   # each touched script
    ```

2. Mutation spot checks, on scratch copies only, never the real files. Each of these
   must fail a test:
    - drop `_configure_environment`'s cookie line, or test `if environment:` instead;
    - drop `APP_ENVIRONMENT` from the prod compose file;
    - drop the badge's `.catch`, or its `APP_TITLE` fallback;
    - drop either `deploy.sh` guard, or the production condition around the hook and
      the units;
    - drop `__BASIC_AUTH__` from the template;
    - drop `--single-transaction`, `DROP SCHEMA`, or the uploads-volume check from
      `copy-production.sh`;
    - drop the `origin/staging` branch from `worktree-setup.sh`;
    - drop the `--nginx` branch from `certbot-setup.sh`.

   Report survivors instead of adding unplanned tests. Moving the badge inside
   `Suspense` is a known survivor: the lazy Login chunk loads within `findByRole`'s
   timeout in tests.
3. Final, in parallel: `npm run test`, `npm run lint`, `npm run lint:py`,
   `npm run lint:md`, `npm run typecheck`, `npm run fallow`, `npm run test:scripts`
   (Docker running, so `test-nginx-site.sh` does not skip), `npx prettier --check .`
   (CI runs it, `ci.yml:121-122`, over every Markdown, YAML, and JSON file), and
   `git diff --check origin/main...HEAD`.
4. Local smoke test, without Docker: `APP_ENVIRONMENT=staging .venv/bin/flask --app
   src_back.app run` and `npm run dev`.
    - `/login` shows the `STAGING` chip at bottom left, and the tab reads
      `STAGING · Flask React Template`.
    - `curl localhost:5000/api/health` returns `"environment": "staging"`.
    - After a sign-in, the cookie is named `staging_session`.
    - With the variable unset, there is no chip and the cookie is `session`.
5. Optional rehearsal of the server scripts in the systemd + Docker container from
   memory `local-server-rehearsal-docker`: two clones side by side, both guards,
   `copy-production.sh`. Let's Encrypt and real TLS cannot run there.
6. After the merge and section 13, on the real server, check the acceptance criteria:
    - Both clones serve.
    - `curl -u tester:<pw> https://<staging>/api/health` reports `staging`, and
      production's reports `production`.
    - The badge shows on staging only.
    - `deploy.sh` refuses the wrong branch and environment.
    - `copy-production.sh` refuses in production's clone and copies on confirmation in
      staging's.
    - `git diff origin/staging origin/main` prints nothing.
