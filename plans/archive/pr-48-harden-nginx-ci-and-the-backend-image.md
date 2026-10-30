# Issue #22: Harden nginx, CI, and the backend image

## Context

Two reviews of derived apps found the same five gaps, and every project generated from
the template inherits them: host nginx sends no security headers and nothing throttles
sign-in attempts, the backend container runs as root, CI audits no dependencies, and
CSRF defense rests on SameSite cookies alone. This PR closes all five.

Three findings widened the issue; Chuck settled each on 2026-10-27:

- Both new audits fail on today's pins, so this PR also upgrades what they flag.
  `pip-audit -r requirements.txt` flags Flask 3.1.0, Flask-Cors 5.0.0, marshmallow
  3.23.0, and python-dotenv 1.0.1. `npm audit --audit-level=high` reports 15 high
  advisories; all but two clear with `npm audit fix`, and those two (js-yaml and
  markdown-it) need markdownlint-cli2 0.23 or newer, which needs Node 22.
- No test runs a real nginx or builds the backend image, so two container tests join
  the shell suite: `test-nginx-site.sh` and `test-backend-image.sh`.
- The nginx limit counts only POSTs under `/api/v1/auth/`, because the SPA sends
  `GET /api/v1/auth/me` on every page load.

An independent design review then added four amendments, which Chuck approved:
`deploy.sh` hands the uploads volume to the backend's user on every redeploy, the dev
image's source changes owner in a `RUN` step instead of `COPY --chown`, the tests cover
more, and three documentation notes.

The issue's last item already holds: no error handler returns `str(exc)`, and
`test_unhandled_exception_returns_json_internal_server_error`
(`src_back/tests/test_app.py:92-103`) proves the generic 500. This PR only makes that
test say so and adds that the exception's text reaches the log.

## Branch

`issue-22-harden-nginx-ci-and-the-backend-image` — already checked out; PR #48 exists.

## Change

**28 files to edit or add**, plus any Markdown file the newer markdownlint flags:
`requirements.txt`, `requirements-dev.txt`, `.node-version` (new), `package.json`,
`package-lock.json`, `.github/workflows/ci.yml`, `scripts/nginx-ssl.conf.template`,
`scripts/deploy.sh`, `scripts/tests/test-deploy.sh`, `scripts/tests/test-nginx-site.sh`
(new), `docker/nginx.conf`, `docker/backend.Dockerfile`, `docker-compose.override.yml`,
`scripts/tests/test-compose-config.sh`, `scripts/tests/test-backend-image.sh` (new),
`src_back/app.py`, `src_back/tests/conftest.py`, `src_back/tests/test_app.py`,
`src_front/src/api/client.ts`, `src_front/src/test/api/client.test.ts`, `README.md`,
`tools.md`, `.env.example`, `ai/conventions.md`, `ai/domain.md`, `ai/auth.md`,
`ai/tls.md`, and `ai/backups.md`.

### .node-version — new: pin Node 22

One line, `22`. markdownlint-cli2 0.23 and newer declare Node 22 or newer, as the
installed lint-staged 17 already does; CI (`ci.yml:83,106,135`), both Node images, and
the dev container already run 22. The local shell runs `fnm env --use-on-cd`, whose
default is Node 20 (end of life since April 2026), and fnm has 22.23.2 installed, so
this file switches the repository to it. Open a new shell in the repository, or run
`fnm use`, and confirm `node --version` prints v22 before any npm command below.

### requirements.txt — upgrade the four flagged pins

Edit lines 3, 8, 10, and 14; leave the rest as they are:

```text
Flask==3.1.3
Flask-Cors==6.0.5
# Stays on 3.x: marshmallow 4 is a breaking release. 3.26.2 fixes CVE-2025-68480.
marshmallow==3.26.2
python-dotenv==1.2.4
```

- Flask 3.1.3 fixes CVE-2025-47278 and CVE-2026-27205.
- Flask-Cors 6.0.5 fixes CVE-2024-6839, CVE-2024-6844, and CVE-2024-6866. Its 6.0
  breaking changes (path-specificity order, case-sensitive paths, `unquote` instead of
  `unquote_plus`) do not touch `CORS(app, origins=..., supports_credentials=True)` with
  the default `/*` resource (`src_back/app.py:209-210`); the `test_cors_*` tests in
  `test_app.py` cover it. 6.0.4 added type hints, so run basedpyright.
- python-dotenv 1.2.4 fixes CVE-2026-28684.

Then `.venv/bin/pip install -r requirements-dev.txt`.

### requirements-dev.txt — add pip-audit

Append `pip-audit==2.10.1` after `pytest-cov==6.1.0` (line 8).

### package.json and package-lock.json — clear the high npm advisories

In order, with Node 22 active:

1. `npm audit fix`, never `--force`. It moves the lock file within the declared ranges:
   axios, vite, zod, react-router, and the transitive brace-expansion, browserslist,
   follow-redirects, form-data, linkify-it, nanoid, postcss, source-map-js, undici, and
   eslint's js-yaml.
2. `npm install --save-dev markdownlint-cli2@^0.24.0`, so line 85 reads
   `"markdownlint-cli2": "^0.24.0"`. It brings markdownlint 0.42, js-yaml 5, and
   markdown-it 15. Do not stop at 0.22.1, which `npm audit` names: it still pins
   js-yaml 4.1.1 and markdown-it 14.1.1, both still under high advisories.
3. `npm audit --audit-level=high` must exit 0. If anything remains, stop and report it
   rather than adding `overrides` or `--force`.

### Markdown files — fix what markdownlint 0.42 newly flags

markdownlint 0.37 to 0.42 adds MD059 (descriptive link text) and MD060 (table column
style). Run `npm run lint:md` and fix each finding in the text. The one table in the
linted files, README's Scripts table (`README.md:167-189`), is already aligned, and no
link text is "here", "link", or "more". Ask before changing `.markdownlint.json`.
lint-staged's `markdownlint-cli2 --fix` (`package.json:46`) keeps working unchanged.

### .github/workflows/ci.yml — add the audits

After the backend job's "Run pytest" step (lines 62-67), as its last step:

```yaml
      # Last, so a newly published advisory never hides the lint and test results.
      # Only the runtime packages are audited: the development tools never reach the
      # image.
      - name: Audit runtime dependencies
        run: .venv/bin/pip-audit -r requirements.txt
```

After the frontend job's "Vitest with coverage" step (lines 121-122), as its last step:

```yaml
      # Last, as in the backend job. devDependencies count too: Vite builds the bundle
      # that ships, and every tool runs on developers' machines and here.
      - name: Audit dependencies
        run: npm audit --audit-level=high
```

Rewrite the scripts job's comment (lines 152-155):

```yaml
      # run-all.sh checks every script's syntax with the shell its shebang names, then
      # runs scripts/tests/. The Compose test renders the stacks with the runner's
      # docker CLI and jq, the nginx site and backend image tests run containers on its
      # Docker daemon, and because Actions sets CI=true, a test that skips itself fails
      # the step.
```

### scripts/nginx-ssl.conf.template — security headers and sign-in throttling

Replace the header comment (lines 1-4), add the `map` and zone above the first
`server`, and add the headers, the 429 envelope, and the `/api/v1/auth/` location to
the HTTPS server. The port-80 server, the 413 block, the `/api|uploads` location, and
`location /` stay as they are:

```nginx
# Host nginx site for the production stack. scripts/deploy.sh renders __APP_NAME__,
# __DOMAIN__, __BACKEND_PORT__, and __FRONTEND_HOST_PORT__ from .env and installs the
# result as /etc/nginx/sites-available/<APP_NAME>. Do not edit the installed copy; it is
# overwritten on every deploy. scripts/tests/test-nginx-site.sh runs it in a real nginx.

# Sign-in throttling for the /api/v1/auth/ location below. Only a POST gets a key, and
# nginx does not count a request whose key is empty, so GET /api/v1/auth/me, which
# every page load sends, is never throttled. Every site on the host shares nginx's
# variable names, so another site that defines this map must define it the same way;
# the zone is named for the app, so each app counts its own attempts.
map $request_method $auth_post_client_address {
    POST    $binary_remote_addr;
    default '';
}
limit_req_zone $auth_post_client_address zone=__APP_NAME__-auth:10m rate=10r/m;

server {
    listen 80;
    # ...unchanged...
}

server {
    listen 443 ssl;
    server_name __DOMAIN__;

    ssl_certificate     /etc/letsencrypt/live/__DOMAIN__/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/__DOMAIN__/privkey.pem;
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         HIGH:!aNULL:!MD5;

    # Every response carries these, nginx's own error pages included (always). A
    # location with an add_header of its own inherits none of them and must repeat all
    # four. deploy.sh refuses to run without the certificate, so HSTS is safe here.
    add_header Strict-Transport-Security "max-age=31536000" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
    add_header Content-Security-Policy "frame-ancestors 'none'" always;

    client_max_body_size 25m;

    # ...the 413 comment, error_page 413, and location @payload_too_large, unchanged...

    # Throttled sign-in attempts get the application's JSON envelope as well.
    error_page 429 = @too_many_requests;
    location @too_many_requests {
        default_type application/json;
        return 429 '{"error": "Too many attempts. Try again in a minute."}';
    }

    # Sign-in POSTs: six at once per client address (one plus a burst of five), then
    # one more every six seconds, and 429 beyond that. ^~ keeps the /api regex below
    # from claiming these paths.
    location ^~ /api/v1/auth/ {
        limit_req zone=__APP_NAME__-auth burst=5 nodelay;
        limit_req_status 429;
        proxy_pass http://127.0.0.1:__BACKEND_PORT__;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # ...the /api|uploads regex location and location /, unchanged...
}
```

Why it is shaped this way:

- HSTS has no `includeSubDomains`, which binds every subdomain of the domain, and no
  `preload`, which asks browsers to build the rule in; both are slow to undo. HSTS
  stays off the port-80 server, where browsers ignore it.
- The headers live only here. Production's host nginx proxies `/api` and `/uploads`
  straight to the backend and only `/` to the frontend container, so headers in
  `docker/nginx.conf` would reach browsers twice on every page.
- No location may ever use `add_header`: `add_header_inherit`, which could merge, only
  arrived in nginx 1.29.3, and Ubuntu ships 1.24.
- A zone name may hold hyphens, so `__APP_NAME__-auth` takes `APP_NAME` as it is. Two
  sites declaring the same zone name would fail `nginx -t`. Variable names cannot hold
  hyphens, so the map keeps one fixed name. nginx's source lets a later `map` of the
  same variable replace an earlier one, which is harmless while every app defines it
  alike; the documentation is silent, so `test-nginx-site.sh` loads two apps' sites
  and checks that each app keeps its own count.
- An upstream's own 429 passes through untouched: without `proxy_intercept_errors`,
  `error_page` applies only to nginx's own responses.

### scripts/deploy.sh — render the app name and hand over the uploads volume

- In the header comment (lines 8-14), after "(starting the database first if the stack
  is stopped)," add "hand the uploads volume to the backend's unprivileged user,",
  rewrapping to 90 columns.
- After `CERT_DIR=...` (line 49), add:

    ```bash
    # The uid the backend image runs as (docker/backend.Dockerfile's useradd --uid);
    # scripts/tests/test-deploy.sh checks that the two agree.
    BACKEND_UID=10001
    ```

- Between the pre-migration backup block (ends line 137) and
  `echo "==> Stopping existing containers..."` (line 139), add:

    ```bash
    # Docker gives a new, empty uploads volume to the backend's user, but never re-owns
    # one that already holds files: files written while the backend ran as root, or
    # restored from an older archive. Saving an upload would then fail while
    # /api/health stays healthy. This runs before the stack goes down, so a failure
    # leaves the old stack serving.
    if [ "$FIRST_DEPLOY" = 0 ]; then
      echo "==> Handing the uploads volume to the backend's user..."
      if ! docker run --rm -v "$UPLOADS_VOLUME:/uploads" alpine \
        chown -R "$BACKEND_UID:$BACKEND_UID" /uploads; then
        echo "ERROR: could not hand $UPLOADS_VOLUME to uid $BACKEND_UID."
        exit 1
      fi
    fi
    ```

- Add the `__APP_NAME__` substitution to the sed at lines 154-157:

    ```bash
    sed -e "s|__APP_NAME__|$APP_NAME|g" -e "s|__DOMAIN__|$DOMAIN|g" \
      -e "s|__BACKEND_PORT__|$BACKEND_PORT|g" \
      -e "s|__FRONTEND_HOST_PORT__|$FRONTEND_HOST_PORT|g" \
      scripts/nginx-ssl.conf.template > "/etc/nginx/sites-available/$NGINX_SITE"
    ```

### scripts/tests/test-deploy.sh — the zone's name, the chown, and the shared uid

- After the `TIMERS` lines (106-109), add:

    ```bash
    # deploy.sh hands the uploads volume to the uid the backend image runs as.
    IMAGE_UID=$(sed -n 's/.*useradd .*--uid \([0-9][0-9]*\).*/\1/p' \
      "$REPO_DIR/docker/backend.Dockerfile")
    [ -n "$IMAGE_UID" ] ||
      { echo 'docker/backend.Dockerfile gives useradd no --uid.' >&2; exit 1; }
    assert_line "$REPO_DIR/scripts/deploy.sh" "BACKEND_UID=$IMAGE_UID"
    CHOWN="docker run --rm -v $UPLOADS_VOLUME:/uploads alpine"
    CHOWN+=" chown -R $IMAGE_UID:$IMAGE_UID /uploads"
    ```

- The docker stub: in its comment (lines 61-66), after the sentence's opening clause
  about finding a volume while its `volume-` flag exists, add "and fails the uploads
  chown while `chown-fails` exists"; in its `case` (lines 77-82), before the
  `"$compose "*)` line, add:

    ```bash
        'run --rm -v '*) [ ! -f "$flags/chown-fails" ] || exit 1 ;;
    ```

- The redeploy case: in its comment (lines 201-205), after "labelled with the commit
  read before the pull," add "hands the uploads volume to the backend's user,"; in its
  call list, add `"$CHOWN" \` after `"backup.sh --pre-migration --label $COMMIT" \`
  (line 217). The first deploy's call list does not change: it has no volume to hand
  over.
- After line 245 (`refute_contains '__[A-Z_]+__' ...`), add:

    ```bash
    # The rate-limit zone is named for the app, so apps sharing the host count apart.
    assert_contains "zone=$APP-auth:10m" "$NGINX_DIR/sites-available/$APP"
    ```

- After the failed-backup case (ends line 282), add:

    ```bash
    # A failed chown of the uploads volume stops the deploy before it takes the stack
    # down, so the old stack keeps serving.
    start_test_case
    add_data_volumes
    touch "$FLAGS/chown-fails"
    expect_failure 'a failed chown of the uploads volume to stop the deploy'
    assert_contains 'could not hand' "$OUTPUT"
    assert_last_command "$CHOWN"
    refute_contains 'down$' "$COMMANDS"
    refute_contains '--build' "$COMMANDS"
    ```

### scripts/tests/test-nginx-site.sh — new: the site in a real nginx

Mode 644, like every test. It renders the template as `deploy.sh` does, for two apps on
one host, and runs it in `nginx:1.27-alpine` behind stub upstreams:

```bash
#!/usr/bin/env bash
# Run scripts/nginx-ssl.conf.template in a real nginx, rendered for two apps on one
# host as scripts/deploy.sh renders it, beside stub upstreams and a throwaway
# certificate per domain. It checks that nginx accepts both sites; that a page, an API
# answer, and nginx's own 429 all carry the four security headers; and that sign-in
# POSTs are throttled per app with a JSON 429, while GETs and other API POSTs never
# are. It needs a running Docker daemon, curl, and openssl; without them it exits 77,
# which scripts/tests/run-all.sh counts as a skip outside CI. It runs under macOS's
# bash 3.2 and on Linux.
set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
for tool in docker curl openssl; do
  command -v "$tool" > /dev/null ||
    { echo "test-nginx-site.sh needs $tool." >&2; exit 77; }
done
docker info > /dev/null 2>&1 ||
  { echo 'test-nginx-site.sh needs a running Docker daemon.' >&2; exit 77; }

# The server runs Ubuntu's nginx package; the production frontend image's nginx, which
# the repository already pulls, stands in for it.
IMAGE=nginx:1.27-alpine
CONTAINER="test-nginx-site-$$"
TEST_DIR=$(mktemp -d)
cleanup() {
  docker rm -f "$CONTAINER" > /dev/null 2>&1 || true
  rm -rf "$TEST_DIR"
}
trap cleanup EXIT
mkdir -p "$TEST_DIR/conf.d"

fail() {
  echo "$1" >&2
  exit 1
}

# Two apps on one host, each rendered as deploy.sh renders the template and each with
# its own certificate. Both proxy to the stub upstreams below.
for app in alpha beta; do
  sed -e "s|__APP_NAME__|$app|g" -e "s|__DOMAIN__|$app.test|g" \
    -e 's|__BACKEND_PORT__|5000|g' -e 's|__FRONTEND_HOST_PORT__|8080|g' \
    "$REPO_DIR/scripts/nginx-ssl.conf.template" > "$TEST_DIR/conf.d/$app.conf"
  if grep -Eq '__[A-Z_]+__' "$TEST_DIR/conf.d/$app.conf"; then
    fail "A placeholder is left in the $app site; render it as deploy.sh does."
  fi
  mkdir -p "$TEST_DIR/letsencrypt/live/$app.test"
  openssl req -x509 -newkey rsa:2048 -nodes -days 1 -subj "/CN=$app.test" \
    -keyout "$TEST_DIR/letsencrypt/live/$app.test/privkey.pem" \
    -out "$TEST_DIR/letsencrypt/live/$app.test/fullchain.pem" > /dev/null 2>&1
done
# Stand-ins for the backend and the frontend container on their loopback ports.
cat > "$TEST_DIR/conf.d/upstreams.conf" <<'NGINX'
server {
    listen 127.0.0.1:5000;
    location / { return 200 'backend'; }
}
server {
    listen 127.0.0.1:8080;
    location / { return 200 'frontend'; }
}
NGINX

# run_nginx DOCKER-RUN-ARG... -> docker run with the sites and certificates mounted.
run_nginx() {
  docker run -v "$TEST_DIR/conf.d:/etc/nginx/conf.d:ro" \
    -v "$TEST_DIR/letsencrypt:/etc/letsencrypt:ro" "$@"
}
run_nginx --rm "$IMAGE" nginx -t > "$TEST_DIR/nginx-t.log" 2>&1 || {
  cat "$TEST_DIR/nginx-t.log" >&2
  fail 'nginx rejected the rendered sites.'
}
run_nginx -d --name "$CONTAINER" -p 127.0.0.1::443 "$IMAGE" > /dev/null
PORT=$(docker port "$CONTAINER" 443/tcp | head -1 | sed 's/.*://')

# fetch APP PATH [CURL-ARG...] -> print the response status; the headers and body land
# in $TEST_DIR/headers and $TEST_DIR/body. --data '' makes the request a POST.
fetch() {
  local app="$1" path="$2" status
  shift 2
  : > "$TEST_DIR/raw-headers"
  status=$(curl -sk --resolve "$app.test:$PORT:127.0.0.1" -D "$TEST_DIR/raw-headers" \
    -o "$TEST_DIR/body" -w '%{http_code}' "$@" "https://$app.test:$PORT$path") || true
  tr -d '\r' < "$TEST_DIR/raw-headers" > "$TEST_DIR/headers"
  echo "$status"
}

# assert_header NAME VALUE -> the last response carried exactly that header line.
assert_header() {
  grep -iqxF "$1: $2" "$TEST_DIR/headers" ||
    fail "The response to the last request lacks '$1: $2'."
}

# assert_security_headers -> the last response carried all four security headers.
assert_security_headers() {
  assert_header Strict-Transport-Security 'max-age=31536000'
  assert_header X-Content-Type-Options nosniff
  assert_header Referrer-Policy strict-origin-when-cross-origin
  assert_header Content-Security-Policy "frame-ancestors 'none'"
}

attempt=0
until [ "$(fetch alpha /)" = 200 ]; do
  attempt=$((attempt + 1))
  if [ "$attempt" -ge 50 ]; then
    docker logs "$CONTAINER" >&2
    fail 'nginx never answered.'
  fi
  sleep 0.2
done
assert_security_headers
[ "$(fetch alpha /api/health)" = 200 ] || fail 'An API GET did not reach the backend.'
assert_security_headers

# Six sign-in POSTs pass at once, one plus a burst of five; the next five get a JSON
# 429 that carries the security headers too. One token returns every six seconds, so
# the count holds while the eleven requests leave within about a second; local curls
# take milliseconds.
statuses=''
for attempt in 1 2 3 4 5 6 7 8 9 10 11; do
  statuses="$statuses $(fetch alpha /api/v1/auth/login --data '')"
done
[ "$statuses" = ' 200 200 200 200 200 200 429 429 429 429 429' ] ||
  fail "Sign-in POSTs answered$statuses, not six 200s and then five 429s."
assert_security_headers
assert_header Content-Type application/json
grep -qxF '{"error": "Too many attempts. Try again in a minute."}' "$TEST_DIR/body" ||
  fail 'The 429 does not carry the JSON error envelope.'

# GETs never count, so /me keeps answering, and POSTs elsewhere under /api are not
# throttled. Each app counts its own attempts, so beta's first sign-in POST passes.
for attempt in 1 2 3 4 5 6 7 8 9 10 11; do
  [ "$(fetch alpha /api/v1/auth/me)" = 200 ] || fail 'A sign-in GET was throttled.'
  [ "$(fetch alpha /api/v1/users --data '')" = 200 ] ||
    fail 'A POST outside /api/v1/auth/ was throttled.'
done
[ "$(fetch beta /api/v1/auth/login --data '')" = 200 ] ||
  fail "One app's sign-in attempts throttled another's."

echo 'nginx site checks passed.'
```

### docker/nginx.conf — say why it sends no security headers

Add above `server {` (line 1), changing nothing else:

```nginx
# The production frontend image's server. Host nginx (scripts/nginx-ssl.conf.template)
# sits in front of it, sends the security headers, and throttles sign-in attempts, so
# this file does neither: headers added here as well would reach browsers twice.
```

### docker/backend.Dockerfile — run as an unprivileged user

The whole file becomes:

```dockerfile
FROM python:3.12-slim

# The app runs as this unprivileged account, never as root. Fixed ids keep the owner of
# the files it writes to the uploads volume the same across rebuilds, and
# scripts/deploy.sh hands that volume to the same uid (BACKEND_UID).
RUN groupadd --system --gid 10001 app \
    && useradd --system --no-log-init --uid 10001 --gid app app

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# The dev stack sets this to watchdog (docker-compose.override.yml): Flask's reloader uses
# it when installed and then sees modules being added and deleted, which its fallback stat
# reloader misses. Production builds leave it empty and install nothing more.
ARG DEVELOPMENT_PACKAGES=
RUN if [ -n "$DEVELOPMENT_PACKAGES" ]; then \
      pip install --no-cache-dir $DEVELOPMENT_PACKAGES; \
    fi

COPY src_back/ ./src_back/
COPY migrations/ ./migrations/
COPY docker/entrypoint.sh docker/entrypoint.sh

# The uploads_data volume mounts here. Docker gives a new, empty volume this directory's
# owner; scripts/deploy.sh hands over one that already holds files.
RUN install -d -o app -g app src_back/uploads

# Production leaves the source owned by root, so the process serving it cannot change
# it. The dev stack builds with SOURCE_OWNER=app (docker-compose.override.yml), because
# Compose's file watch writes and deletes files, and creates them in every synced
# directory, as the container's user.
ARG SOURCE_OWNER=root
RUN if [ "$SOURCE_OWNER" != root ]; then \
      chown -R "$SOURCE_OWNER:$SOURCE_OWNER" src_back migrations docker; \
    fi

USER app

EXPOSE 5000

CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "src_back.app:create_app()"]
```

- The `RUN chown` mirrors the `DEVELOPMENT_PACKAGES` idiom. `COPY --chown` with a
  build argument was the first draft, but Docker documents variable expansion only for
  `--chmod`, and file watch also needs `app` to own the directories COPY creates, such
  as `/app/docker`.
- uid 10001 sits above the range ordinary host accounts use, so a file the container
  writes is unlikely to map to a real user on the host. `--no-log-init` keeps the
  account out of lastlog and faillog, which Docker's best-practices guide warns can
  bloat a layer when the uid is large.
- `.dockerignore` already excludes `src_back/uploads` (lines 15-17), so `install -d`
  makes a fresh directory.
- Python cannot write `__pycache__` beside root-owned source and silently compiles in
  memory instead; that costs little at start-up and needs no change.

### docker-compose.override.yml — give the dev image's source to the app user

Under `backend.build.args` (after line 16):

```yaml
        # File watch writes and deletes the synced files as the container's user, so the
        # dev image gives the source to the app user; production keeps it root's.
        SOURCE_OWNER: app
```

### scripts/tests/test-compose-config.sh — SOURCE_OWNER and no user override

- In the header comment (lines 2-10), change "carries file watch and watchdog" to
  "carries file watch, watchdog, and backend source owned by the app user", and add
  that neither stack overrides the image's user, rewrapping to 90 columns.
- After the watchdog check (lines 54-55):

    ```bash
    # File watch writes the synced files as the container's user, the app user.
    check dev '.services.backend.build.args.SOURCE_OWNER == "app"' \
      'backend source owned by the app user'
    ```

- After the development-packages check (lines 76-77):

    ```bash
    check prod '(.services.backend.build.args.SOURCE_OWNER // "") == ""' \
      'backend source left to root'
    # The backend runs as the image's unprivileged user (docker/backend.Dockerfile).
    for stack in dev prod; do
      check "$stack" '.services.backend | has("user") | not' \
        'no user override on the backend'
    done
    ```

### scripts/tests/test-backend-image.sh — new: the image as built

Mode 644:

```bash
#!/usr/bin/env bash
# Build the backend image as production builds it and as the dev stack builds it, and
# check who runs the app and who owns its files: the unprivileged app user (uid 10001)
# runs every container; the production source belongs to root, so the process serving
# it cannot change it; all of the dev source belongs to the app user, as Compose's file
# watch needs; a new, empty volume on the uploads directory is writable by the app
# user; and one that already holds root's files is not, until the chown that
# scripts/deploy.sh runs hands it over. It needs a running Docker daemon; without one
# it exits 77, which scripts/tests/run-all.sh counts as a skip outside CI. It runs
# under macOS's bash 3.2 and on Linux.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."
docker info > /dev/null 2>&1 ||
  { echo 'test-backend-image.sh needs a running Docker daemon.' >&2; exit 77; }

IMAGE="test-backend-image-$$"
NEW_VOLUME="test-backend-image-new-$$"
OLD_VOLUME="test-backend-image-old-$$"
cleanup() {
  docker volume rm -f "$NEW_VOLUME" "$OLD_VOLUME" > /dev/null 2>&1 || true
  docker image rm -f "$IMAGE:production" "$IMAGE:development" > /dev/null 2>&1 || true
}
trap cleanup EXIT

fail() {
  echo "$1" >&2
  exit 1
}

docker build --quiet --file docker/backend.Dockerfile --tag "$IMAGE:production" . \
  > /dev/null
# The dev stack's build argument (docker-compose.override.yml); watchdog is irrelevant.
docker build --quiet --file docker/backend.Dockerfile --build-arg SOURCE_OWNER=app \
  --tag "$IMAGE:development" . > /dev/null

# run_in TAG COMMAND [ARG...] -> run COMMAND in a throwaway container of the image, as
# the image's own user, from its working directory, /app.
run_in() {
  local tag="$1" command="$2"
  shift 2
  docker run --rm --entrypoint "$command" "$IMAGE:$tag" "$@"
}

# app_can_write VOLUME -> the app user can create a file in VOLUME, mounted on the
# production image's uploads directory.
app_can_write() {
  docker run --rm -v "$1:/app/src_back/uploads" --entrypoint touch \
    "$IMAGE:production" src_back/uploads/probe 2> /dev/null
}

for tag in production development; do
  [ "$(run_in "$tag" id -u)" = 10001 ] ||
    fail "The $tag image does not run as uid 10001."
  [ "$(run_in "$tag" stat -c %U src_back/uploads)" = app ] ||
    fail "The app user does not own src_back/uploads in the $tag image."
  # Both stacks start the backend with /bin/sh docker/entrypoint.sh.
  run_in "$tag" sh -n docker/entrypoint.sh ||
    fail "The app user cannot read docker/entrypoint.sh in the $tag image."
done
for path in src_back src_back/app.py migrations docker docker/entrypoint.sh; do
  [ "$(run_in production stat -c %U "$path")" = root ] ||
    fail "root does not own $path in the production image."
done
if run_in production touch src_back/probe 2> /dev/null; then
  fail 'The app user can write the production source.'
fi
# File watch writes, deletes, and creates files in every synced directory.
UNOWNED=$(run_in development find src_back migrations docker ! -user app) ||
  fail 'find failed in the development image.'
[ -z "$UNOWNED" ] ||
  fail "The app user does not own these in the development image: $UNOWNED"

# Docker gives a new, empty named volume the owner of the image directory it mounts on.
docker volume create "$NEW_VOLUME" > /dev/null
app_can_write "$NEW_VOLUME" || fail 'The app user cannot write to a new uploads volume.'

# A volume that already holds root's files keeps root as its owner until the chown
# scripts/deploy.sh runs hands it over.
docker run --rm -v "$OLD_VOLUME:/uploads" alpine touch /uploads/old-upload
if app_can_write "$OLD_VOLUME"; then
  fail 'The app user could write to a volume that root owns.'
fi
docker run --rm -v "$OLD_VOLUME:/uploads" alpine chown -R 10001:10001 /uploads
app_can_write "$OLD_VOLUME" ||
  fail "deploy.sh's chown does not hand an old uploads volume to the app user."

echo 'Backend image checks passed.'
```

The first build installs `requirements.txt` (about a minute on a cold runner); the
second reuses every layer up to its own `chown`.

### src_back/app.py — reject unmarked mutating API requests

- Imports: after line 23, `from src_back.utils import ErrorResponse, forbidden`.
  `src_back/utils.py` imports only `extensions` and `models` from the package, so there
  is no cycle.
- After line 36 (`_JSON_PATH_PREFIXES`):

    ```python
    _MUTATING_METHODS = frozenset({'POST', 'PUT', 'PATCH', 'DELETE'})
    ```

- In `create_app`, after `_register_blueprints(app)` (line 96), add
  `app.before_request(_require_requested_with_header)`; the function grows to 26
  lines. It must stay an app-level hook: Flask runs those before routing raises 404 or
  405, so it also covers a mutating request to a path or method no route accepts,
  while a blueprint's hook would never see one.
- `_is_json_path` (lines 278-292) now serves the hook as well as the 404 handler: change
  its summary line to "Decide whether a path belongs to the API or the upload store."
- After `_is_json_path`, add:

    ```python
    def _require_requested_with_header() -> ErrorResponse | None:
        """Refuse a mutating API request that lacks the SPA's X-Requested-With header.

        Defense in depth against cross-site request forgery, under the SameSite
        session cookie: a form on another site cannot set the header, and a script on
        another origin cannot send it without a CORS preflight that only the allowed
        origins pass. ``ai/conventions.md`` explains when a route may be exempted.

        Returns:
            A 403 JSON error envelope for a POST, PUT, PATCH, or DELETE to an ``/api``
            or ``/uploads`` path that lacks ``X-Requested-With: XMLHttpRequest``,
            otherwise ``None``, which lets the request through.
        """
        if (
            request.method in _MUTATING_METHODS
            and _is_json_path(request.path)
            and request.headers.get('X-Requested-With') != 'XMLHttpRequest'
        ):
            return forbidden('Missing the X-Requested-With header.')
        return None
    ```

The check covers `/uploads` because it reuses the one whole-segment matcher; no route
there accepts a mutating method, so it only turns their HTML 405 into a JSON 403. Do not
build an exemption mechanism now: #30 adds the one route that needs it, and an unused
one would be untested code under the 100% gate.

### src_back/tests/conftest.py — every test client sends the header

- Add `from typing import Any` to the imports (lines 1-3).
- After `WidgetNote` (line 42), add:

    ```python
    class SpaTestClient(FlaskClient):
        """Test client that sends X-Requested-With on every request, as the SPA does."""

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            self.environ_base['HTTP_X_REQUESTED_WITH'] = 'XMLHttpRequest'
    ```

- In the `app` fixture, between `create_app(...)` (line 55) and the `with` block:

    ```python
        # Every client the tests build, app.test_client() included, marks its requests as
        # the SPA's axios client does, which mutating API requests need.
        app.test_client_class = SpaTestClient
    ```

`client`, `auth_client`, `admin_client`, and the three tests that build their own
client and sign in (`test_app.py:135`, `test_users_api.py:35`, `test_users_api.py:225`)
all get the header this way, with no edit of their own. Tests that call `create_app`
directly only send GETs.

### src_back/tests/test_app.py — the header check and the 500's log

Tighten the 500 test (lines 92-103): take `caplog: pytest.LogCaptureFixture`, send the
request inside `with caplog.at_level(logging.ERROR, logger='src_back.app'):` (the style
of lines 267-276), keep both existing asserts, and add:

```python
    # The exception's text goes to the log, never to the client.
    assert b'deliberate failure' not in response.data
    assert 'deliberate failure for the 500 handler' in caplog.text
```

After `test_oversized_request_body_returns_json_file_too_large` (ends line 131), add:

```python
@pytest.mark.parametrize('method', ['POST', 'PUT', 'PATCH', 'DELETE'])
@pytest.mark.parametrize('path', ['/api', '/api/v1/auth/login', '/uploads/photo.png'])
def test_mutating_request_without_requested_with_header_is_forbidden(
    client: FlaskClient, method: str, path: str
) -> None:
    client.environ_base.pop('HTTP_X_REQUESTED_WITH')
    response = client.open(path, method=method, json={})
    assert response.status_code == 403
    assert response.get_json() == {'error': 'Missing the X-Requested-With header.'}


def test_sign_in_without_requested_with_header_starts_no_session(
    client: FlaskClient, user: User
) -> None:
    client.environ_base.pop('HTTP_X_REQUESTED_WITH')
    response = client.post(
        '/api/v1/auth/login', json={'email': user.email, 'password': 'password123'}
    )
    assert response.status_code == 403
    assert 'Set-Cookie' not in response.headers


def test_requested_with_header_must_name_xmlhttprequest(client: FlaskClient) -> None:
    response = client.post('/api/v1/auth/logout', headers={'X-Requested-With': 'fetch'})
    assert response.status_code == 403


def test_marked_mutating_request_reaches_its_route(client: FlaskClient) -> None:
    # Anonymous, so logout's @login_required answers rather than the header check.
    response = client.post('/api/v1/auth/logout')
    assert response.status_code == 401


@pytest.mark.parametrize(
    ('method', 'path', 'status'),
    [
        ('GET', '/api/health', 200),
        ('OPTIONS', '/api/v1/auth/login', 200),
        ('POST', '/api-docs', 405),
        ('POST', '/some-client-route', 405),
    ],
)
def test_safe_methods_and_spa_paths_need_no_requested_with_header(
    client: FlaskClient, method: str, path: str, status: int
) -> None:
    client.environ_base.pop('HTTP_X_REQUESTED_WITH')
    response = client.open(path, method=method)
    assert response.status_code == status
```

A per-request `headers=` value wins over `environ_base`, which is how the third test
sends a wrong value. The 405s are Flask's static rule refusing a POST, as today. The
second test is login CSRF: a forged sign-in with valid credentials starts no session.

### src_front/src/api/client.ts — send the header

- In `axios.create` (lines 26-33), add `'X-Requested-With': 'XMLHttpRequest'` after
  `'Content-Type': 'application/json'`.
- In the `@file` block (lines 1-9), after the `withCredentials` sentence, add: "Every
  request also sends `X-Requested-With: XMLHttpRequest`, which the backend requires on
  any request that changes data: a form on another site cannot set it, so a forged
  request fails."

### src_front/src/test/api/client.test.ts — assert it

After the Content-Type test (lines 61-63):

```ts
    it('marks every request as an XMLHttpRequest for the CSRF check', () => {
        expect(client.defaults.headers['X-Requested-With']).toBe('XMLHttpRequest')
    })
```

### .env.example — say what `*` costs

Replace the CORS comment (line 22) with:

```text
# Comma-separated allowed frontend origins. "*" permits all (dev only): it also lets any
# site pass the CORS preflight for X-Requested-With, voiding the CSRF header check
# (ai/conventions.md), so production lists only its own origin.
```

### ai/conventions.md — record why

After the Auth bullet in the Backend section (ends line 63), insert:

````markdown
- Every POST, PUT, PATCH, or DELETE to `/api` or `/uploads` must carry
  `X-Requested-With: XMLHttpRequest`, which the axios client sends on every request;
  `_require_requested_with_header` in `app.py` answers any other with 403. It is CSRF
  defense in depth. SameSite cookies keep other sites' requests from carrying the
  session, but a sibling subdomain counts as the same site, and an older browser may
  ignore SameSite. A form cannot set a custom header, and a script on another origin
  cannot send one without a CORS preflight, which only the origins in
  `CORS_ALLOWED_ORIGINS` pass: production sets it to the site's own origin, while
  development's `*` passes every origin. A route that must accept a cross-site POST,
  such as Sign in with Apple's `form_post` callback (#30), must be exempted in that
  hook and check its own `state` instead.
````

Three smaller edits in the same file:

- API Responses, lines 95-96: add `429` to the list of error statuses, and after
  "Validation failures are `422`." add "Host nginx answers throttled sign-in POSTs with
  `429` (`ai/auth.md`)."
- Frontend, line 104: "uses `baseURL: '/api'` and `withCredentials`" becomes "uses
  `baseURL: '/api'`, `withCredentials`, and the `X-Requested-With: XMLHttpRequest`
  header that the backend requires on every request that changes data".
- Shell Scripts: after the Bash 3.2 bullet (ends line 176), insert:

````markdown
- A test that needs a real server or image, as `test-nginx-site.sh` and
  `test-backend-image.sh` do, runs containers instead of stubs. It names every
  container, image, and volume it creates after itself and its process id, removes
  them however it exits, and exits 77 without a running Docker daemon or a tool it
  needs.
````

### ai/domain.md — the test clients send the header

After the fixture list (ends line 36), insert:

````markdown
The `app` fixture sets `app.test_client_class` to `SpaTestClient`, so every client the
tests build, `app.test_client()` included, sends `X-Requested-With: XMLHttpRequest` as
the SPA does. To send a request without it, pop `HTTP_X_REQUESTED_WITH` from the
client's `environ_base`.
````

### ai/auth.md — throttling and the header for sign-in providers

In the Overview list, after the Self-registration bullet (ends line 24), insert:

````markdown
- Every POST under `/api` must carry `X-Requested-With: XMLHttpRequest`
  (`ai/conventions.md`). Sign in with Apple's `form_post` callback (#30) arrives as a
  cross-site POST without it, so #30 must exempt that route and check its `state`
  instead.
````

Before `## Deactivated accounts` (line 32), insert:

````markdown
## Sign-in throttling

In production, host nginx counts the POSTs each client address sends under
`/api/v1/auth/`: six may arrive at once, then one more every six seconds, and nginx
answers the rest with 429 and `{"error": "Too many attempts. Try again in a minute."}`
(`scripts/nginx-ssl.conf.template`). GETs never count, so `/me`, which every page load
sends, is never throttled. Development has no nginx and no limit.

- Every POST under `/api/v1/auth/` shares the budget, including later ones such as the
  passkey ceremonies (#32) and Sign in with Apple's callback (#30). A sign-in that
  takes two POSTs leaves a user three attempts at once.
- The limit keys on the address nginx sees. Behind a CDN or another proxy, that is the
  proxy's address, so configure `real_ip_header` and `set_real_ip_from` first.
- Each app on a host has its own zone, named for `APP_NAME`. The `map` that picks out
  POSTs defines `$auth_post_client_address`, a name every site on the host shares, so
  another site that defines it must define it the same way.

To check it on the server, send eleven quick POSTs. The app answers the first six (422,
for the empty body) and nginx the other five (429):

```bash
for i in $(seq 11); do
  curl -s -o /dev/null -w '%{http_code} ' -X POST \
    -H 'X-Requested-With: XMLHttpRequest' "https://$DOMAIN/api/v1/auth/login"
done; echo
```
````

### ai/tls.md — the security headers and HSTS

Before `## Verifying` (line 73), insert:

````markdown
## Security headers

The HTTPS server in `scripts/nginx-ssl.conf.template` adds four headers to every
response, nginx's own error pages included:

- `Strict-Transport-Security: max-age=31536000`
- `X-Content-Type-Options: nosniff`
- `Referrer-Policy: strict-origin-when-cross-origin`
- `Content-Security-Policy: frame-ancestors 'none'`

Only host nginx sends them. The frontend container's `docker/nginx.conf` sits behind it
and adds none, so no header arrives twice. A location that sets an `add_header` of its
own inherits none of the four and must repeat them.

HSTS is a promise kept for a year: a browser that has seen it refuses plain HTTP to
`$DOMAIN` and no longer lets a visitor click through a certificate error. An expired
certificate then takes the site down for every returning visitor instead of showing a
warning, which makes the monitoring above essential. Undoing HSTS needs a valid
certificate too: serve `max-age=0` over HTTPS until every returning browser has seen
it. The header leaves out `includeSubDomains`, which binds every subdomain, and
`preload`, which asks browsers to build the rule in; both are slow to undo, so add them
only once every subdomain serves HTTPS.
````

At the end of the second Verifying block (after line 88), add:

```bash
curl -sI https://$DOMAIN/ |
  grep -iE '^(strict-transport|x-content-type|referrer|content-security)'
```

### ai/backups.md — restored uploads belong to the app user

Step 4 (lines 235-240): end the intro sentence with ". The `chown` hands every file to
the backend's unprivileged user (uid 10001), including files from an archive made while
the backend still ran as root, since an archive keeps each file's numeric owner:" and
make the command:

```bash
docker run --rm -v <COMPOSE_PROJECT_NAME>_uploads_data:/to -v /tmp:/from alpine \
  sh -c 'rm -rf /to/* && tar xzf /from/<up-file> -C /to && chown -R 10001:10001 /to'
```

Keep the block's existing four-space indentation.

### README.md — the unprivileged backend

In the Docker section, after the paragraph that ends at line 120, insert:

````markdown
The backend runs as the unprivileged `app` user (uid 10001), never as root. Its source
belongs to root in production, so the running app cannot change it; the dev image
gives it to `app`, because file watch writes the synced files as that user.
````

In the Uploads section, after line 263, insert:

````markdown
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
````

In the Deployment section:

- After "only nginx faces the network." (line 268), add: "Host nginx also sends the
  security headers and throttles sign-in attempts; `ai/tls.md` and `ai/auth.md`
  describe both."
- In "`scripts/deploy.sh` backs up the database before migrating, rebuilds the
  containers," (lines 281-282), add "hands the uploads volume to the backend's
  unprivileged user," before "rebuilds the containers".

### tools.md — the new tools and what changed

- Node.js entry (lines 19-22): after "CI and the dev container pin 22," add
  "`.node-version` asks version managers such as fnm for 22,".
- After pytest-cov (lines 109-110), add: "- **pip-audit**: checks the packages in
  `requirements.txt`, and those they pull in, against PyPI's vulnerability data. CI's
  backend job fails on any known vulnerability; run it locally with
  `.venv/bin/pip-audit -r requirements.txt`."
- Shell script tests (lines 215-222): in the first bullet, after "checks the rendered
  Compose stacks instead", add "and `test-nginx-site.sh` and `test-backend-image.sh`
  run real containers". Add a bullet: "- **Docker daemon, curl, and openssl**:
  `test-nginx-site.sh` runs the host site template, rendered for two apps, in
  `nginx:1.27-alpine` with throwaway certificates and sends it requests with curl;
  `test-backend-image.sh` builds the backend image and runs it beside `alpine`. The CI
  runner has all three; locally, each test skips without them."
- `python:3.12-slim` (lines 242-244): add "It runs the app as the unprivileged `app`
  user, uid 10001."
- `nginx:1.27-alpine` (lines 247-249): add "Host nginx sits in front of it and sends
  the security headers, so it adds none. `test-nginx-site.sh` runs the host site in
  this image too."
- `alpine` (lines 255-256): add that `scripts/deploy.sh` uses it to hand the uploads
  volume to the backend's user, and `test-backend-image.sh` to stand in for an old
  volume.
- GitHub Actions (lines 260-266): the backend list ends "pytest against a PostgreSQL
  service, and pip-audit"; the frontend list ends "Vitest, and `npm audit` at high
  severity".
- Host nginx (lines 284-287): "terminates TLS, and proxies" becomes "terminates TLS,
  sends the security headers, throttles sign-in POSTs, and proxies".

## Parallelism

**Must be sequential, first: Group A (dependencies, Node, CI).** `.node-version`,
`requirements.txt`, `requirements-dev.txt`, `package.json`, `package-lock.json`, the
markdownlint fixes, and `ci.yml`. Every later test run needs the upgraded packages, and
the documentation edits must pass the newer markdownlint.

**Can be done in parallel after Group A** (no shared files):

- Group B (infrastructure): the nginx template, `deploy.sh`, `test-deploy.sh`,
  `test-nginx-site.sh`, `docker/nginx.conf`, the Dockerfile, the override,
  `test-compose-config.sh`, and `test-backend-image.sh`. One group, because
  `test-deploy.sh` reads the Dockerfile's uid and `deploy.sh` serves both the nginx and
  the image changes.
- Group C (CSRF and the 500): `app.py`, `conftest.py`, `test_app.py`, `client.ts`, and
  `client.test.ts`. Add the hook and `SpaTestClient` together: the hook alone fails
  every mutating test.
- Group D (documentation): `README.md`, `tools.md`, `.env.example`, and the five `ai/`
  files. Every name it cites is fixed in this plan, so it need not wait for B or C.

**Must be sequential, last:** the full verification below.

## No other changes needed

- The error handlers (`app.py:38-44`, `230-258`, `295-305`) return fixed messages. The
  service messages that `api/auth.py:41,68` and `api/users.py:52,73,75` return are
  written for users and stay.
- `docker/entrypoint.sh` and `test-entrypoint.sh`: nothing in the entrypoint needs root.
  The migrations and the seed reach Postgres over the network, and both servers bind
  port 5000.
- `backup.sh`, `restore-drill.sh`, and `test-backup.sh`: the backup's alpine container
  reads the volume as root, whoever owns the files, and the drill only lists archives.
- `deploy.sh` already runs `nginx -t` before it reloads (lines 163-164).
- No route needs an exemption from the header check yet: nothing receives a cross-site
  POST. The frontend sends no request outside the axios instance, and the Vite proxy
  and both nginx configs pass the header through. A 429 needs no frontend handling:
  `surfaceApiError` already shows its `error` text on the sign-in form.
- `docker/nginx.Dockerfile` and `docker/frontend.Dockerfile` stay; the frontend
  containers are outside this issue.

Follow-ups, not in this PR, each worth an issue of its own:

- `CORS_ALLOWED_ORIGINS` defaults to `*` in `app.py:209` and `.env.example:23`, and
  with `supports_credentials=True` Flask-Cors then echoes any origin. Production is
  safe only because `provision.sh` writes `https://$DOMAIN`; a start-up guard like
  `_guard_secret_key` that refuses `*` outside development would close it.
- `deploy.sh` writes the site into `sites-enabled` before `nginx -t` (lines 154-163),
  so a failed test leaves the broken file in place for the next reload of any app on
  the host, certbot's included, and for the next boot. Restoring the previous file on
  failure would close it.

## Risks

- nginx's documentation never says whether two sites may define the same `map`
  variable. If `nginx -t` in `test-nginx-site.sh` rejects the second app's map, stop and
  report; the fallback is a per-app variable name, which needs another placeholder.
- The container tests pull `nginx:1.27-alpine`, `python:3.12-slim`, and `alpine` from
  Docker Hub in CI, as the backend job already pulls `postgres:16`; a pull limit would
  fail the scripts job, not skip it.
- `npm audit fix` moves many packages at once. If the frontend suite or the build
  breaks on one of them, report it rather than pinning around it.
- The deploy's `chown -R` runs on every redeploy, before the stack goes down; on a
  volume of many thousands of files it adds seconds.

## Verification

1. `node --version` prints v22 in the repository.
2. `.venv/bin/pip install -r requirements-dev.txt`, then
   `.venv/bin/pip-audit -r requirements.txt` reports no known vulnerabilities, and
   `npm audit --audit-level=high` exits 0.
3. The audits fail on a vulnerable pin: a scratch requirements file holding
   `Flask==3.1.0` makes `.venv/bin/pip-audit -r <that file>` exit 1 and name
   GHSA-4grg-w6v8-c28g. The issue's version of this check, a deliberately old pin
   pushed on a throwaway branch, is Chuck's to run, since agents never push.
4. Targeted runs while working, with Docker Desktop running:
    - `.venv/bin/python -m pytest --no-cov` (the conftest change touches every test)
    - `npx vitest run src_front/src/test/api/client.test.ts`
    - `bash scripts/tests/test-deploy.sh`, `bash scripts/tests/test-compose-config.sh`,
      `bash scripts/tests/test-nginx-site.sh`, and
      `bash scripts/tests/test-backend-image.sh`; neither container test may print a
      skip.
5. Mutations each test must catch, tried on scratch copies only: an unnamed zone
   (`zone=auth`), a dropped `always`, a map that keys GETs too, a missing `^~`, no
   `USER app`, `SOURCE_OWNER` dropped from the override, the dev `chown` dropped from
   the Dockerfile, the deploy's chown dropped, the uid changed in only the Dockerfile,
   the hook not registered, and the header missing from `client.ts`. Report survivors
   instead of adding tests this plan does not list.
6. Full checks, in parallel: `npm run test`, `npm run lint -- --max-warnings=0`,
   `npm run lint:py`, `npm run lint:md`, `npm run test:scripts`, `npm run build`,
   `npx prettier --check .`, and `npm run fallow`.
7. Dev stack: start `npm run docker:up` as a background command, then:
    - `docker compose exec backend id -u` prints 10001.
    - Edit a backend module, add a new one, delete it, and change
      `docker/entrypoint.sh`: each syncs, and the watch output shows no permission
      error.
    - `docker compose exec backend sh -c 'printf probe > src_back/uploads/probe.txt'`
      succeeds; signed in through the UI (`npm run docker:url`), `/uploads/probe.txt`
      shows "probe". Remove the probe. If the write is refused, the local volume
      already held files; run README's chown command once.
    - From the host, a POST to `/api/v1/auth/login` on the frontend port without
      `X-Requested-With` answers 403, and with it 422 for an empty body; signing in
      through the UI works.
    - `npm run docker:down`.
8. After merge and deploy, on the server (Chuck): `curl -sI https://$DOMAIN/` shows the
   four headers, the loop in `ai/auth.md` prints six app answers and five 429s, the
   backend's `id -u` prints 10001, and
   `docker run --rm -v <COMPOSE_PROJECT_NAME>_uploads_data:/u alpine stat -c %u /u`
   prints 10001.
