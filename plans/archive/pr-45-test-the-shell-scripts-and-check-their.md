# Issue #15: Test the shell scripts and check their syntax in CI

## Context

`scripts/` and `docker/entrypoint.sh` carry much of the template's value, and nothing
tests them: CI never runs `bash -n` or `sh -n`, so a typo in `deploy.sh` surfaces on the
server. This ports hukilau's shell-script harness (`scripts/tests/`, hukilau PRs #34
and #46): tests that run a script against logging stub commands and assert on the log.
Hukilau's four matching tests target its later scripts (compose watch, a LAN stack,
local daily backups), so each test here is written for the template's current
`up.sh`, `entrypoint.sh`, `backup.sh`, and Compose files rather than copied. Two
hukilau weaknesses are fixed on the way. Its CI step lists scripts by hand, which
drifted once (hukilau `c090d40`) and still skips 13 scripts; here a runner finds every
script by its shebang. Its `test-backup.sh` exits 1 off Linux; here it exits 77, which
the runner treats as a skip locally and as a failure in CI, so
`npm run test:scripts` passes on a Mac while CI still runs every test.

## Branch

`issue-15-test-the-shell-scripts-and-check-their`, already checked out; PR #45 exists.
Per #27, Sonnet 5.5 runs the `/implement-plan` group agents.

## Change

**11 files**: create `scripts/tests/run-all.sh`, `scripts/tests/test-up.sh`,
`scripts/tests/test-entrypoint.sh`, `scripts/tests/test-compose-config.sh`, and
`scripts/tests/test-backup.sh`; edit `.github/workflows/ci.yml`, `package.json`,
`ai/conventions.md`, `ai/project.md`, `README.md`, and `tools.md`.

Shared rules for the five new files, taken from hukilau's harness:

- Mode 644, run as `bash <file>`, as hukilau's tests are (its PR #46). Do not
  `chmod +x` them.
- 2-space indentation, as `scripts/*.sh` use, and lines of 90 characters or fewer.
- Every file except `test-backup.sh` must run under macOS's `/bin/bash` 3.2.57, the
  default `bash` on this Mac. Do not use `mapfile`, associative arrays, `${var,,}`,
  `sed -i`, `grep -P`, `tail -z`, or `((n++))` (it returns 1 at zero and trips `set -e`).
- Under `set -e`, a failing command in an `&&` list exits nothing unless it is the
  last command, and a bare `! grep` never fails. Stubs therefore signal failure with
  `[ ... ] || exit 1`, and tests assert through `assert_contains`/`refute_contains`.
- Every stub is checked to shadow the real command before the script runs. An unshadowed
  `docker` in `test-up.sh` would start the real dev stack, and an unshadowed `rclone`
  in `test-backup.sh` could reach a real bucket.

### scripts/tests/run-all.sh (new): syntax checks, then every test

`npm run test:scripts` and the CI job both run this file, so the two cannot diverge.
`git ls-files --cached --others --exclude-standard` lists the tracked files plus new
unignored ones (209 files today, all text; husky's `.husky/_/` is ignored by its own
`.gitignore`). Today the shebang scan finds 17 scripts: the 7 `#!/bin/sh` files are
`.husky/pre-commit`, `.husky/pre-push`, `docker/entrypoint.sh`, `scripts/docker-url.sh`,
`scripts/down.sh`, `scripts/up.sh`, and `scripts/worktree-setup.sh`; the other 10 are
Bash. All 17 already pass `sh -n` or `bash -n` under macOS's bash 3.2, and none uses
bash-4-only syntax (`|&`, `;&`, `;;&`).

```bash
#!/usr/bin/env bash
# Check the syntax of every shell script in the repository with the shell its shebang
# names, then run each scripts/tests/test-*.sh. A test that cannot run on this machine,
# because it needs Linux or a tool that is missing, says why and exits 77: a skip
# locally, but a failure in CI, so CI runs every test. `npm run test:scripts` and CI
# both run this file; it runs under macOS's bash 3.2 and on Linux.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."
failures=0
checked=0

# Tracked files plus new ones git does not ignore, so a script is checked before it is
# committed. The listing is captured on its own line because set -e cannot see a git
# failure inside a process substitution, which would pass as an empty list.
files=$(git ls-files --cached --others --exclude-standard)
while IFS= read -r file; do
  [ -f "$file" ] || continue
  first_line=
  IFS= read -r first_line < "$file" || true
  case $first_line in
    '#!/bin/sh'* | '#!/usr/bin/env sh'*) shell=sh ;;
    '#!/bin/bash'* | '#!/usr/bin/env bash'*) shell=bash ;;
    *)
      # Nothing says which shell checks a .sh file without a shebang.
      case $file in
        *.sh)
          echo "FAIL $file has no sh or bash shebang" >&2
          failures=$((failures + 1))
          ;;
      esac
      continue
      ;;
  esac
  checked=$((checked + 1))
  if ! "$shell" -n "$file"; then
    echo "FAIL $shell -n $file" >&2
    failures=$((failures + 1))
  fi
done <<< "$files"
echo "Checked the syntax of $checked scripts."

for test_file in scripts/tests/test-*.sh; do
  status=0
  bash "$test_file" || status=$?
  case $status in
    0) echo "PASS $test_file" ;;
    77)
      if [ "${CI:-}" = true ]; then
        echo "FAIL $test_file skipped itself, and CI runs every test" >&2
        failures=$((failures + 1))
      else
        echo "SKIP $test_file"
      fi
      ;;
    *)
      echo "FAIL $test_file exited $status" >&2
      failures=$((failures + 1))
      ;;
  esac
done

if [ "$failures" -gt 0 ]; then
  echo "$failures shell script check(s) failed." >&2
  exit 1
fi
echo 'All shell script checks passed.'
```

`read` takes the first line rather than `$(head -n 1)`, which warns about NUL bytes
in bash 4.4+ if a binary file is ever tracked. GitHub Actions always sets `CI=true`.

### scripts/tests/test-up.sh (new): port assignment, running stack, production

Covers `scripts/up.sh:10-69`. It runs the real `up.sh` with `sh` from a disposable
repository holding a copy of the real `.env.example`. On CI that `sh` is dash, so the
test also proves `up.sh` stays POSIX. It is adapted from hukilau's `test-up.sh` without
hukilau's `--build --watch` assertions, which belong to #13.

```bash
#!/usr/bin/env bash
# Exercise scripts/up.sh's port assignment, its already-running path, and its
# production path with stub docker and lsof commands. It runs under macOS's bash 3.2
# and on Linux in CI, so it avoids bash 4 features.
set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TEST_DIR=$(mktemp -d)
trap 'rm -rf "$TEST_DIR"' EXIT
mkdir -p "$TEST_DIR/bin" "$TEST_DIR/repo"
EXAMPLE="$TEST_DIR/repo/.env.example"
cp "$REPO_DIR/.env.example" "$EXAMPLE"
export TEST_DIR
export PATH="$TEST_DIR/bin:$PATH"
ENV_FILE="$TEST_DIR/repo/.env"
COMMANDS="$TEST_DIR/commands"
OUTPUT="$TEST_DIR/output"

# docker logs each call to $TEST_DIR/commands and reports a running stack while
# $TEST_DIR/running exists.
cat > "$TEST_DIR/bin/docker" <<'MOCK'
#!/usr/bin/env bash
set -eu
printf 'docker %s\n' "$*" >> "$TEST_DIR/commands"
if [ "$*" = 'compose ps -q' ] && [ -f "$TEST_DIR/running" ]; then
  echo 0123456789ab
fi
MOCK
# lsof, called as `lsof -i TCP:<port> -sTCP:LISTEN -n -P`, reports a listener on each
# port listed in $TEST_DIR/busy-ports.
cat > "$TEST_DIR/bin/lsof" <<'MOCK'
#!/usr/bin/env bash
set -eu
port=${2#TCP:}
if grep -qx "$port" "$TEST_DIR/busy-ports" 2>/dev/null; then
  echo "com.docke 4242 user 9u IPv4 0x1 0t0 TCP *:$port (LISTEN)"
fi
MOCK
chmod +x "$TEST_DIR/bin/docker" "$TEST_DIR/bin/lsof"
# A stub that did not come first on PATH would let up.sh start the real stack.
for command in docker lsof; do
  [ "$(command -v "$command")" = "$TEST_DIR/bin/$command" ] ||
    { echo "The $command stub does not shadow the real command." >&2; exit 1; }
done

# set_busy_ports [PORT...] -> lsof reports exactly these ports in use.
set_busy_ports() {
  printf '%s\n' "$@" > "$TEST_DIR/busy-ports"
}

# Run up.sh from the disposable repository, as `npm run docker:up -- <arguments>` does,
# and show its output if it fails.
run_up() {
  : > "$COMMANDS"
  (cd "$TEST_DIR/repo" && sh "$REPO_DIR/scripts/up.sh" "$@") > "$OUTPUT" 2>&1 ||
    { echo "up.sh${*:+ $*} failed:" >&2; cat "$OUTPUT" >&2; exit 1; }
}

# A bare `! grep` never fails under set -e, so both checks exit explicitly.
assert_contains() {
  grep -Eq -- "$1" "$2" || { echo "Missing /$1/ in ${2##*/}" >&2; exit 1; }
}

refute_contains() {
  if grep -Eq -- "$1" "$2"; then echo "Unexpected /$1/ in ${2##*/}" >&2; exit 1; fi
}

# A first start writes .env from the example, moves a busy database port, and points
# DATABASE_URL at the new one; the free ports keep the example's values.
set_busy_ports 5432
run_up
assert_contains '^DB_PORT=5433$' "$ENV_FILE"
assert_contains '^DATABASE_URL=postgresql://app:app@localhost:5433/app$' "$ENV_FILE"
assert_contains '^BACKEND_PORT=5000$' "$ENV_FILE"
assert_contains '^VITE_API_URL=http://localhost:5000$' "$ENV_FILE"
assert_contains '^FRONTEND_PORT=5174$' "$ENV_FILE"
assert_contains '^PUBLIC_BASE_URL=http://localhost:5174$' "$ENV_FILE"
assert_contains 'Port assignment:' "$OUTPUT"
assert_contains '^docker compose ps -q$' "$COMMANDS"
assert_contains '^docker compose up$' "$COMMANDS"

# Busy backend and frontend ports carry VITE_API_URL and PUBLIC_BASE_URL with them, and
# PUBLIC_BASE_URL keeps its trailing slash.
sed 's|^PUBLIC_BASE_URL=.*|PUBLIC_BASE_URL=http://localhost:5174/|' "$EXAMPLE" \
  > "$ENV_FILE"
set_busy_ports 5000 5174
run_up
assert_contains '^DB_PORT=5432$' "$ENV_FILE"
assert_contains '^BACKEND_PORT=5001$' "$ENV_FILE"
assert_contains '^VITE_API_URL=http://localhost:5001$' "$ENV_FILE"
assert_contains '^FRONTEND_PORT=5175$' "$ENV_FILE"
assert_contains '^PUBLIC_BASE_URL=http://localhost:5175/$' "$ENV_FILE"

# A blank PUBLIC_BASE_URL gets the frontend's origin, and a public one is left alone.
sed 's|^PUBLIC_BASE_URL=.*|PUBLIC_BASE_URL=|' "$EXAMPLE" > "$ENV_FILE"
set_busy_ports
run_up
assert_contains '^PUBLIC_BASE_URL=http://localhost:5174$' "$ENV_FILE"
sed 's|^PUBLIC_BASE_URL=.*|PUBLIC_BASE_URL=https://app.example.com|' "$EXAMPLE" \
  > "$ENV_FILE"
set_busy_ports 5174
run_up
assert_contains '^FRONTEND_PORT=5175$' "$ENV_FILE"
assert_contains '^PUBLIC_BASE_URL=https://app\.example\.com$' "$ENV_FILE"

# An .env from before VITE_API_URL and PUBLIC_BASE_URL existed gains both lines.
grep -v -E '^(VITE_API_URL|PUBLIC_BASE_URL)=' "$EXAMPLE" > "$ENV_FILE"
set_busy_ports
run_up
assert_contains '^VITE_API_URL=http://localhost:5000$' "$ENV_FILE"
assert_contains '^PUBLIC_BASE_URL=http://localhost:5174$' "$ENV_FILE"

# Ports start from .env, so a worktree's shifted ports stay while they are free, and
# up.sh hands its arguments to docker compose up.
sed -e 's/^DB_PORT=.*/DB_PORT=5442/' -e 's/^BACKEND_PORT=.*/BACKEND_PORT=5010/' \
  -e 's/^FRONTEND_PORT=.*/FRONTEND_PORT=5184/' "$EXAMPLE" > "$ENV_FILE"
set_busy_ports
run_up -d backend
assert_contains '^DB_PORT=5442$' "$ENV_FILE"
assert_contains '^DATABASE_URL=postgresql://app:app@localhost:5442/app$' "$ENV_FILE"
assert_contains '^BACKEND_PORT=5010$' "$ENV_FILE"
assert_contains '^FRONTEND_PORT=5184$' "$ENV_FILE"
assert_contains '^PUBLIC_BASE_URL=http://localhost:5184$' "$ENV_FILE"
assert_contains '^docker compose up -d backend$' "$COMMANDS"

# A running stack keeps the ports in .env, even one that now looks busy, and still
# starts.
cp "$EXAMPLE" "$ENV_FILE"
cp "$ENV_FILE" "$TEST_DIR/before.env"
set_busy_ports 5000
touch "$TEST_DIR/running"
run_up
cmp -s "$TEST_DIR/before.env" "$ENV_FILE" ||
  { echo 'up.sh rewrote .env while the stack was running.' >&2; exit 1; }
assert_contains 'Stack already running; keeping the ports in \.env\.' "$OUTPUT"
refute_contains 'Port assignment' "$OUTPUT"
assert_contains '^docker compose up$' "$COMMANDS"
rm "$TEST_DIR/running"

# Production assigns no ports, even with one busy, and starts as asked.
sed 's/^FLASK_ENV=.*/FLASK_ENV=production/' "$EXAMPLE" > "$ENV_FILE"
cp "$ENV_FILE" "$TEST_DIR/before.env"
set_busy_ports 5432
run_up -d
cmp -s "$TEST_DIR/before.env" "$ENV_FILE" ||
  { echo 'up.sh rewrote .env in production.' >&2; exit 1; }
refute_contains 'Port assignment|Stack already running' "$OUTPUT"
assert_contains '^docker compose up -d$' "$COMMANDS"

echo 'up.sh regression checks passed.'
```

### scripts/tests/test-entrypoint.sh (new): migrate, seed, gunicorn

Covers `docker/entrypoint.sh:1-17`. The template's entrypoint has no development branch
yet, so this keeps hukilau's stubs and failure cases and drops its Flask-reloader case.
Issue #13 adds the development branch and its test.

```bash
#!/usr/bin/env bash
# Exercise docker/entrypoint.sh with stub flask, python, and gunicorn commands. It runs
# under macOS's bash 3.2 and on Linux in CI, so it avoids bash 4 features; CI's sh is
# dash, as the backend image's is.
set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TEST_DIR=$(mktemp -d)
trap 'rm -rf "$TEST_DIR"' EXIT
mkdir -p "$TEST_DIR/bin"
export TEST_DIR
export PATH="$TEST_DIR/bin:$PATH"
COMMANDS="$TEST_DIR/commands"

# Each stub logs its call to $TEST_DIR/commands and fails while $TEST_DIR/fail-<name>
# exists.
cat > "$TEST_DIR/bin/mock-command" <<'MOCK'
#!/usr/bin/env bash
set -eu
name=${0##*/}
printf '%s %s\n' "$name" "$*" >> "$TEST_DIR/commands"
[ ! -f "$TEST_DIR/fail-$name" ]
MOCK
chmod +x "$TEST_DIR/bin/mock-command"
# A stub that did not come first on PATH would let the entrypoint reach a real database.
for command in flask python gunicorn; do
  ln -s mock-command "$TEST_DIR/bin/$command"
  [ "$(command -v "$command")" = "$TEST_DIR/bin/$command" ] ||
    { echo "The $command stub does not shadow the real command." >&2; exit 1; }
done

MIGRATE='flask --app src_back.app db upgrade'
SEED='python -m src_back.seed'
GUNICORN='gunicorn --bind 0.0.0.0:5000 --workers 2 --access-logfile -'
GUNICORN="$GUNICORN src_back.app:create_app()"

# run_entrypoint [NAME=value...] -> run the entrypoint with FLASK_ENV and
# GUNICORN_WORKERS cleared and the given variables set, logging the stubs' calls afresh.
run_entrypoint() {
  : > "$COMMANDS"
  env -u FLASK_ENV -u GUNICORN_WORKERS "$@" sh "$REPO_DIR/docker/entrypoint.sh" \
    > "$TEST_DIR/output" 2>&1
}

# expect_calls LINE... -> the stubs ran exactly these lines, in this order.
expect_calls() {
  printf '%s\n' "$@" | diff -u - "$COMMANDS"
}

# The entrypoint migrates, seeds, and then runs gunicorn, with two workers unless
# GUNICORN_WORKERS, which the production override sets, says otherwise.
run_entrypoint
expect_calls "$MIGRATE" "$SEED" "$GUNICORN"
run_entrypoint FLASK_ENV=production
expect_calls "$MIGRATE" "$SEED" "$GUNICORN"
run_entrypoint FLASK_ENV=production GUNICORN_WORKERS=4
expect_calls "$MIGRATE" "$SEED" "${GUNICORN/--workers 2/--workers 4}"

# A failed migration or seed stops the container before gunicorn starts.
touch "$TEST_DIR/fail-flask"
if run_entrypoint; then
  echo 'Expected a failed migration to stop the entrypoint.' >&2
  exit 1
fi
expect_calls "$MIGRATE"
rm "$TEST_DIR/fail-flask"

touch "$TEST_DIR/fail-python"
if run_entrypoint; then
  echo 'Expected a failed seed to stop the entrypoint.' >&2
  exit 1
fi
expect_calls "$MIGRATE" "$SEED"
rm "$TEST_DIR/fail-python"

echo 'Entrypoint regression checks passed.'
```

### scripts/tests/test-compose-config.sh (new): the production stack's contract

Renders both stacks with `docker compose config --format json` (no daemon needed) and
checks them with `jq`. On this Mac, Compose v5.4.0 renders a production port as
`{"host_ip": "127.0.0.1", "target": 5000, "published": "5000", ...}` and omits
`host_ip` when no address is given. That bare form, like `0.0.0.0`, binds every
interface. The production `db.ports` renders as `null` (`!reset []`), and
`build.dockerfile` stays relative (`docker/nginx.Dockerfile`). This covers the issue's
acceptance criterion: the test fails if the production stack publishes on `0.0.0.0` or
loses `GUNICORN_WORKERS`.

```bash
#!/usr/bin/env bash
# Render the development and production Compose configurations and check what the
# production stack must keep: loopback-only ports and no database port, a production
# backend with GUNICORN_WORKERS and secure session cookies, and the nginx frontend. It
# needs the docker CLI with Compose, and jq, but no daemon; without them it exits 77,
# which scripts/tests/run-all.sh counts as a skip outside CI. It runs under macOS's
# bash 3.2 and on Linux.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."
if ! docker compose version > /dev/null 2>&1 || ! command -v jq > /dev/null; then
  echo 'test-compose-config.sh needs the docker CLI with Compose, and jq.' >&2
  exit 77
fi
TEST_DIR=$(mktemp -d)
trap 'rm -rf "$TEST_DIR"' EXIT

# Placeholders for the variables the production override requires. An empty env file
# keeps a developer's .env out of the renders, and the shell must not supply the files
# or the values the checks read.
unset COMPOSE_FILE GUNICORN_WORKERS SESSION_COOKIE_SECURE SESSION_COOKIE_SAMESITE
: > "$TEST_DIR/empty.env"
export POSTGRES_USER=app POSTGRES_PASSWORD=app POSTGRES_DB=app SECRET_KEY=placeholder \
  DATABASE_URL=postgresql://app:app@db:5432/app CORS_ALLOWED_ORIGINS=http://localhost \
  PUBLIC_BASE_URL=http://localhost

render() {
  docker compose --env-file "$TEST_DIR/empty.env" "$@" config --format json
}

render > "$TEST_DIR/dev.json"
render -f docker-compose.yml -f docker/docker-compose.prod.yml > "$TEST_DIR/prod.json"
(
  export GUNICORN_WORKERS=3
  render -f docker-compose.yml -f docker/docker-compose.prod.yml
) > "$TEST_DIR/prod-workers.json"

# check STACK FILTER EXPECTATION -> fail unless jq's FILTER holds for STACK's render.
check() {
  jq -e "$2" "$TEST_DIR/$1.json" > /dev/null || {
    echo "The $1 configuration should have $3." >&2
    exit 1
  }
}

check dev '.services.backend.environment.FLASK_ENV == "development"' \
  'a development backend'
check dev '.services.frontend.build.dockerfile == "docker/frontend.Dockerfile"' \
  'the Vite dev server as its frontend'
# A port without host_ip binds every interface, as 0.0.0.0 does. The count keeps the
# loopback check from passing on a stack that publishes nothing.
check prod '[.services[].ports[]?] | length > 0' 'published ports'
check prod '[.services[].ports[]? | .host_ip == "127.0.0.1"] | all' \
  'every published port bound to 127.0.0.1'
check prod '(.services.db.ports // []) | length == 0' 'no published database port'
check prod '.services.backend.environment.FLASK_ENV == "production"' \
  'a production backend'
check prod '.services.backend.environment.GUNICORN_WORKERS == "4"' \
  'GUNICORN_WORKERS, 4 by default'
check prod-workers '.services.backend.environment.GUNICORN_WORKERS == "3"' \
  'the GUNICORN_WORKERS its .env gives'
check prod '.services.backend.environment.SESSION_COOKIE_SECURE == "true"' \
  'secure session cookies by default'
check prod '.services.backend.environment.SESSION_COOKIE_SAMESITE == "Strict"' \
  'strict SameSite session cookies by default'
check prod '.services.frontend.build.dockerfile == "docker/nginx.Dockerfile"' \
  'the nginx image as its frontend'

echo 'Compose configuration checks passed.'
```

### scripts/tests/test-backup.sh (new): daily and pre-migration modes

Covers `scripts/backup.sh:11-147`, which is byte-identical to hukilau's original. The
template's daily mode differs from hukilau's current one: it fails without the remote
(`backup.sh:106`) and keeps no local daily copies. Hukilau's cases would therefore fail
from the first; these cases are written for the template's behaviour. `/var/log` and
`/var/backups` are rewritten into the test directory with `sed`, the only absolute
paths in the script. A `date` stub pins the weekday and day of the month, so the
weekly and monthly pushes (`backup.sh:123-124`) are exercised deterministically rather
than only on Sundays and the 1st. Markers in `$TEST_DIR/flags/` drive the stubs, and
each case starts from an empty flag directory.

```bash
#!/usr/bin/env bash
# Exercise scripts/backup.sh's daily and pre-migration modes: the real script runs in a
# disposable copy of the repository, with stub docker, rclone, df, hostname, and date
# commands and a stub scripts/alert.sh. It is Linux-only: backup.sh needs bash 4
# (mapfile) and GNU tail -z, and the rclone stub uses GNU find -printf, none of which
# macOS has. Elsewhere it exits 77, which scripts/tests/run-all.sh counts as a skip
# outside CI. CI runs it directly; on a Mac, run it in a container from the repository
# root:
#   docker run --rm -v "$PWD:/repo" -w /repo debian:trixie \
#     bash scripts/tests/test-backup.sh
set -euo pipefail
if [ "$(uname -s)" != Linux ]; then
  echo 'test-backup.sh runs only on Linux; its header gives the container command.' >&2
  exit 77
fi
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TEST_DIR=$(mktemp -d)
trap 'rm -rf "$TEST_DIR"' EXIT
mkdir -p "$TEST_DIR/bin" "$TEST_DIR/repo/scripts"
# Redirect the host's backup and log directories into the disposable test directory.
sed -e "s|/var/backups|$TEST_DIR/backups|g" -e "s|/var/log|$TEST_DIR/log|g" \
  "$REPO_DIR/scripts/backup.sh" > "$TEST_DIR/repo/scripts/backup.sh"
REAL_DATE=$(command -v date)
export TEST_DIR REAL_DATE
export PATH="$TEST_DIR/bin:$PATH"
FLAGS="$TEST_DIR/flags"
ENV_FILE="$TEST_DIR/repo/.env"
COMMANDS="$TEST_DIR/commands"
LOG="$TEST_DIR/log/flask-react-template/backup.log"
PRE_MIGRATION="$TEST_DIR/backups/flask-react-template/pre-migration"
BUCKET_DIR="$TEST_DIR/bucket/test-bucket/prod"
REMOTE='spaces:test-bucket/prod'
STAMP='[0-9]{8}T[0-9]{6}Z'
DUMP='^docker compose -f docker-compose\.yml -f docker/docker-compose\.prod\.yml'
DUMP+=' --env-file \.env exec -T db pg_dump -U app -d app -Fc$'
ARCHIVE='^docker run --rm -v flask-react-template_uploads_data:/from:ro -v .*:/backup'
ARCHIVE+=" alpine tar czf /backup/uploads-$STAMP\.tar\.gz -C /from \.$"

# Each stub logs its call to $TEST_DIR/commands and reads its conditions from markers
# in $TEST_DIR/flags. docker stands in for the dump, the volume check, and the archive,
# and finds no uploads volume while no-uploads-volume exists. rclone treats
# $TEST_DIR/bucket as the spaces: remote, which it lists while remote-configured exists
# and cannot reach while remote-unreachable exists; its uploads also fail while
# upload-fails exists. df reports ample free space, or 1000 KB while low-disk exists.
cat > "$TEST_DIR/bin/mock-system" <<'MOCK'
#!/usr/bin/env bash
set -eu
name=${0##*/}
flags="$TEST_DIR/flags"
printf '%s\n' "$name $*" >> "$TEST_DIR/commands"
bucket_path() { printf '%s\n' "$TEST_DIR/bucket/${1#spaces:}"; }
case "$name" in
  df)
    available=100000000
    [ ! -f "$flags/low-disk" ] || available=1000
    echo 'Filesystem 1024-blocks Used Available Capacity Mounted on'
    echo "mock 100000000 0 $available 0% /"
    ;;
  hostname) echo test-host ;;
  docker)
    if [[ "$*" = 'compose '*' exec -T db pg_dump '* ]]; then
      echo 'PGDMP and filler standing in for a custom-format dump'
    elif [[ "$*" = 'volume inspect '* ]]; then
      [ ! -f "$flags/no-uploads-volume" ] || exit 1
    elif [[ "$*" = 'run '*' alpine tar czf /backup/'* ]]; then
      # Write the archive tar would create into the directory mounted at /backup.
      for argument in "$@"; do
        case "$argument" in
          *:/backup) directory=${argument%:/backup} ;;
          /backup/*) archive=${argument#/backup/} ;;
        esac
      done
      echo 'uploads archive' > "$directory/$archive"
    else
      echo "Unexpected docker call: $*" >&2
      exit 1
    fi
    ;;
  rclone)
    case "$1" in
      listremotes) [ ! -f "$flags/remote-configured" ] || echo 'spaces:' ;;
      lsd)
        [ -f "$flags/remote-configured" ] || exit 1
        [ ! -f "$flags/remote-unreachable" ] || exit 1
        ;;
      copyto)
        [ ! -f "$flags/remote-unreachable" ] || exit 1
        [ ! -f "$flags/upload-fails" ] || exit 1
        mkdir -p "$(dirname "$(bucket_path "$3")")"
        cp "$2" "$(bucket_path "$3")"
        ;;
      # lsf --files-only <directory> lists file names; a missing directory has none.
      lsf)
        directory=$(bucket_path "$3")
        [ ! -d "$directory" ] || find "$directory" -maxdepth 1 -type f -printf '%f\n'
        ;;
      deletefile) rm "$(bucket_path "$2")" ;;
      *) echo "Unexpected rclone call: $*" >&2; exit 1 ;;
    esac
    ;;
  *) echo "Unexpected mock command: $name" >&2; exit 1 ;;
esac
MOCK
# date answers the weekday (+%u) and the day of the month (+%d) from the weekday and
# day-of-month markers, a Wednesday the 15th unless a case writes them, so only the case
# that asks pushes weekly and monthly copies. Every other call goes to the real date,
# unlogged.
cat > "$TEST_DIR/bin/date" <<'MOCK'
#!/usr/bin/env bash
set -eu
case "$*" in
  '-u +%u') cat "$TEST_DIR/flags/weekday" 2>/dev/null || echo 3 ;;
  '-u +%d') cat "$TEST_DIR/flags/day-of-month" 2>/dev/null || echo 15 ;;
  *) exec "$REAL_DATE" "$@" ;;
esac
MOCK
chmod +x "$TEST_DIR/bin/mock-system" "$TEST_DIR/bin/date"
for command in docker rclone df hostname; do
  ln -s mock-system "$TEST_DIR/bin/$command"
done
# A stub that did not come first on PATH would let backup.sh reach a real database or a
# real bucket.
for command in docker rclone df hostname date; do
  [ "$(command -v "$command")" = "$TEST_DIR/bin/$command" ] ||
    { echo "The $command stub does not shadow the real command." >&2; exit 1; }
done

# Stand-in for scripts/alert.sh: logs the subject and body it was given.
cat > "$TEST_DIR/repo/scripts/alert.sh" <<'ALERT'
#!/usr/bin/env bash
printf 'alert.sh %s\n' "$*" >> "$TEST_DIR/commands"
ALERT

# Start a case from empty backup, bucket, log, and flag directories, so the remote is
# unconfigured and the day ordinary; a fresh command log; and a .env holding what
# backup.sh requires plus any given lines, which win because backup.sh reads the last
# one. Two runs in the same second share a timestamp, so no case may see another's
# files.
start_test_case() {
  rm -rf "$TEST_DIR/backups" "$TEST_DIR/bucket" "$TEST_DIR/log" "$FLAGS"
  mkdir -p "$TEST_DIR/backups" "$TEST_DIR/bucket" "$FLAGS"
  : > "$COMMANDS"
  printf '%s\n' APP_NAME=flask-react-template COMPOSE_PROJECT_NAME=flask-react-template \
    POSTGRES_USER=app POSTGRES_DB=app "$@" > "$ENV_FILE"
}

# Run the copy's backup.sh, which writes its output to $LOG; show the log on failure.
run_backup() {
  bash "$TEST_DIR/repo/scripts/backup.sh" "$@" ||
    { echo "backup.sh${*:+ $*} failed. Its log:" >&2; cat "$LOG" >&2; exit 1; }
}

# expect_failure DESCRIPTION [ARGUMENT...] -> the run fails. backup.sh writes to $LOG
# once it knows APP_NAME; anything it prints before that lands in $TEST_DIR/stderr.
expect_failure() {
  local description=$1
  shift
  if bash "$TEST_DIR/repo/scripts/backup.sh" "$@" 2> "$TEST_DIR/stderr"; then
    echo "Expected $description." >&2
    exit 1
  fi
}

# A bare `! grep` never fails under set -e, so both checks exit explicitly.
assert_contains() {
  grep -Eq -- "$1" "$2" || { echo "Missing /$1/ in ${2##*/}" >&2; exit 1; }
}

refute_contains() {
  if grep -Eq -- "$1" "$2"; then echo "Unexpected /$1/ in ${2##*/}" >&2; exit 1; fi
}

# assert_failure_reported MODE REASON -> the run logged `FAILURE: REASON` and called
# alert.sh exactly once, with the subject for a failed MODE backup, the reason, and the
# host.
assert_failure_reported() {
  local alerts subject="flask-react-template: $1 backup FAILED"
  assert_contains "FAILURE: $2" "$LOG"
  alerts=$(grep -c '^alert\.sh ' "$COMMANDS") || true
  [ "$alerts" -eq 1 ] ||
    { echo "Expected one alert.sh call, found $alerts" >&2; exit 1; }
  assert_contains "^alert\.sh $subject $2.* \(host test-host\)" "$COMMANDS"
}

# assert_file_count COUNT DIRECTORY PATTERN -> exactly COUNT files in DIRECTORY have
# names matching PATTERN.
assert_file_count() {
  local found
  found=$(find "$2" -maxdepth 1 -type f -name "$3" 2>/dev/null | wc -l) || true
  [ "$found" -eq "$1" ] ||
    { echo "Expected $1 files matching $3 in ${2##*/}, found $found" >&2; exit 1; }
}

# seed_older_backups DIRECTORY PREFIX SUFFIX COUNT -> COUNT files named for consecutive
# days from 2020-01-01, all older than any run's timestamp.
seed_older_backups() {
  local day
  mkdir -p "$1"
  for (( day = 1; day <= $4; day++ )); do
    touch "$1/$2-202001$(printf '%02d' "$day")T000000Z$3"
  done
}

# Daily mode needs the remote: without one, the run takes the dump, then fails and
# alerts before it archives the uploads.
start_test_case
expect_failure 'a daily run without a remote to fail'
assert_contains "$DUMP" "$COMMANDS"
assert_failure_reported daily 'Spaces not configured/reachable'
refute_contains '^docker (volume|run) ' "$COMMANDS"

# A configured remote that cannot be reached fails the run the same way.
start_test_case SPACES_BUCKET=test-bucket
touch "$FLAGS/remote-configured" "$FLAGS/remote-unreachable"
expect_failure 'a daily run with an unreachable remote to fail'
assert_contains '^rclone lsd spaces:test-bucket$' "$COMMANDS"
assert_failure_reported daily 'Spaces not configured/reachable'
refute_contains '^docker (volume|run) ' "$COMMANDS"

# With the remote, a daily run archives the uploads volume COMPOSE_PROJECT_NAME names and
# pushes both files to daily/, which keeps the newest RETAIN_DAILY of each kind, this
# run's included. An ordinary weekday pushes no weekly or monthly copy.
start_test_case SPACES_BUCKET=test-bucket RETAIN_DAILY=2
touch "$FLAGS/remote-configured"
seed_older_backups "$BUCKET_DIR/daily/db" db .dump 3
seed_older_backups "$BUCKET_DIR/daily/uploads" uploads .tar.gz 3
run_backup
assert_contains "$DUMP" "$COMMANDS"
assert_contains "$ARCHIVE" "$COMMANDS"
assert_contains "^rclone copyto .* $REMOTE/daily/db/db-$STAMP\.dump$" "$COMMANDS"
assert_contains "^rclone copyto .* $REMOTE/daily/uploads/uploads-$STAMP\.tar\.gz$" \
  "$COMMANDS"
refute_contains "^rclone copyto .* $REMOTE/(weekly|monthly)/" "$COMMANDS"
assert_contains "SUCCESS: db-$STAMP\.dump \+ uploads-$STAMP\.tar\.gz uploaded" "$LOG"
assert_file_count 2 "$BUCKET_DIR/daily/db" 'db-*.dump'
assert_file_count 2 "$BUCKET_DIR/daily/uploads" 'uploads-*.tar.gz'
assert_file_count 1 "$BUCKET_DIR/daily/db" 'db-2020*'
assert_file_count 1 "$BUCKET_DIR/daily/uploads" 'uploads-2020*'
refute_contains '^alert\.sh ' "$COMMANDS"

# On a Sunday that is the first of the month, the run also pushes weekly and monthly
# copies, and each tier keeps its own newest RETAIN_WEEKLY and RETAIN_MONTHLY, set
# apart so that swapping the two would show.
start_test_case SPACES_BUCKET=test-bucket RETAIN_WEEKLY=1 RETAIN_MONTHLY=2
touch "$FLAGS/remote-configured"
echo 7 > "$FLAGS/weekday"
echo 01 > "$FLAGS/day-of-month"
seed_older_backups "$BUCKET_DIR/weekly/db" db .dump 2
seed_older_backups "$BUCKET_DIR/monthly/uploads" uploads .tar.gz 2
run_backup
for tier in weekly monthly; do
  assert_contains "^rclone copyto .* $REMOTE/$tier/db/db-$STAMP\.dump$" "$COMMANDS"
  assert_contains "^rclone copyto .* $REMOTE/$tier/uploads/uploads-$STAMP\.tar\.gz$" \
    "$COMMANDS"
done
assert_file_count 1 "$BUCKET_DIR/weekly/db" 'db-*.dump'
assert_file_count 0 "$BUCKET_DIR/weekly/db" 'db-2020*'
assert_file_count 2 "$BUCKET_DIR/monthly/uploads" 'uploads-*.tar.gz'
assert_file_count 1 "$BUCKET_DIR/monthly/uploads" 'uploads-2020*'

# A missing uploads volume fails the run instead of archiving an empty one.
start_test_case SPACES_BUCKET=test-bucket
touch "$FLAGS/remote-configured" "$FLAGS/no-uploads-volume"
expect_failure 'a missing uploads volume to fail the run'
assert_failure_reported daily \
  'uploads volume flask-react-template_uploads_data not found'
refute_contains '^docker run |^rclone copyto' "$COMMANDS"

# A failed upload inside push() reaches the ERR trap, which set -E carries into
# functions, so the run still fails with exactly one alert.
start_test_case SPACES_BUCKET=test-bucket
touch "$FLAGS/remote-configured" "$FLAGS/upload-fails"
expect_failure 'a failed upload to fail the run'
assert_failure_reported daily 'error at line [0-9]+'
refute_contains 'SUCCESS' "$LOG"

# The run checks its settings and free space before it dumps anything. An empty
# APP_NAME goes to stderr, since APP_NAME locates the log; an empty COMPOSE_PROJECT_NAME
# or less than ~2 GB free fails the run with an alert.
start_test_case APP_NAME=
expect_failure 'an empty APP_NAME to fail the run'
assert_contains 'ERROR: APP_NAME is empty' "$TEST_DIR/stderr"
refute_contains '^(docker|alert\.sh) ' "$COMMANDS"
start_test_case COMPOSE_PROJECT_NAME=
expect_failure 'an empty COMPOSE_PROJECT_NAME to fail the run'
assert_failure_reported daily 'COMPOSE_PROJECT_NAME is not set'
refute_contains '^docker ' "$COMMANDS"
start_test_case
touch "$FLAGS/low-disk"
expect_failure 'low free space to fail the run'
assert_failure_reported daily 'less than ~2GB free'
refute_contains '^docker ' "$COMMANDS"

# A pre-migration dump keeps the newest three on the host and warns without a remote,
# and it neither archives the uploads nor checks the remote.
start_test_case
seed_older_backups "$PRE_MIGRATION" db .dump 4
run_backup --pre-migration
assert_file_count 3 "$PRE_MIGRATION" 'db-*.dump'
assert_file_count 2 "$PRE_MIGRATION" 'db-2020*'
assert_file_count 0 "$PRE_MIGRATION" 'db-2020010[12]T*'
assert_contains 'WARN: Spaces remote not configured yet; kept LOCAL pre-migration' "$LOG"
refute_contains '^docker (volume|run) |^rclone (lsd|copyto)' "$COMMANDS"

# With the remote configured, the dump also goes to premigration/ in the bucket.
start_test_case SPACES_BUCKET=test-bucket
touch "$FLAGS/remote-configured"
run_backup --pre-migration
assert_file_count 1 "$PRE_MIGRATION" 'db-*.dump'
assert_contains "^rclone copyto .* $REMOTE/premigration/db-$STAMP\.dump$" "$COMMANDS"
assert_file_count 1 "$BUCKET_DIR/premigration" 'db-*.dump'
assert_contains 'pre-migration backup OK \(local \+ Spaces\)' "$LOG"

# Once the remote is configured, a failed push fails the deploy's backup instead of
# falling back to the local copy, which is still written.
start_test_case SPACES_BUCKET=test-bucket
touch "$FLAGS/remote-configured" "$FLAGS/remote-unreachable"
expect_failure 'a failed pre-migration push to fail the run' --pre-migration
assert_failure_reported pre-migration 'Spaces push failed for pre-migration dump'
assert_file_count 1 "$PRE_MIGRATION" 'db-*.dump'

echo 'Backup regression checks passed.'
```

The failed-upload case pins the `set -E` the comment at `backup.sh:43-48` depends on.
Without errtrace, `set -e` exits from inside `push()` before the caller's ERR trap
runs, so no FAILURE line is logged and no alert is sent.

### .github/workflows/ci.yml: a shell-script job and a manual trigger

Add `workflow_dispatch` to the `on:` block (lines 3-7):

```yaml
on:
  push:
    branches: ['**']
  pull_request:
    branches: ['**']
  # Runs every job on a chosen branch from the Actions tab.
  workflow_dispatch:
```

Append a fifth job after `build` (after line 140). It gets its own job rather than a
step inside "Python lint + test" (where hukilau put it) because it needs no Python
or Node setup, runs in parallel, and a failure is reported under its own name:

```yaml
  scripts:
    name: Shell scripts
    runs-on: ubuntu-latest
    timeout-minutes: 15

    steps:
      - uses: actions/checkout@v7

      # run-all.sh checks every script's syntax with the shell its shebang names, then
      # runs scripts/tests/. The Compose test renders the stacks with the runner's
      # docker CLI and jq, and because Actions sets CI=true, a test that skips itself
      # fails the step.
      - name: Shell script checks
        run: bash scripts/tests/run-all.sh
```

The runner needs jq and Compose 2.24.4 or newer for the production file's `!reset` and
`!override` tags. Hukilau's CI renders a production file with the same tags through
its own `test-compose-config.sh` on `ubuntu-latest` without installing anything, and
every recent run passed (latest 2026-10-23).

### package.json: test:scripts

After `"test:back"` (line 20):

```json
    "test:scripts": "bash scripts/tests/run-all.sh",
```

`"test"` stays `run-p test:front test:back`; the issue adds only `test:scripts`.

### ai/conventions.md: the rule for scripts

Insert a section before `## Git` (line 160):

```markdown
## Shell Scripts

- Every new or changed shell script gets a test, `scripts/tests/test-<script>.sh`, in
  the style of the existing ones. The test runs the script against a disposable
  directory, copying the script there and rewriting absolute system paths such as
  `/var/log` with `sed` when it writes to them. It puts stub commands (`docker`,
  `systemctl`, `lsof`, `rclone`, `curl`, and so on) first on `PATH`, checks that each
  shadows the real command, and has each log its call to a `commands` file. It asserts
  on that log, and on the files the script wrote, with grep-based `assert_contains` and
  `refute_contains`, because a bare `! grep` never fails under `set -e`, or with `diff`
  when the exact sequence of calls matters, as `test-entrypoint.sh` does.
- Tests run under macOS's Bash 3.2 as well as on Linux, so they avoid `mapfile`,
  associative arrays, `${var,,}`, `sed -i`, `grep -P`, and GNU-only options such as
  `tail -z` and `find -printf`. A test that cannot run on the machine, because its
  script needs Linux, as `backup.sh` does, or a tool is missing, says why and exits
  with status 77. `scripts/tests/run-all.sh` counts that as a skip locally and as a
  failure in CI, where every test must run.
- Every script names its shell in a shebang (`#!/bin/sh`, `#!/bin/bash`, or
  `#!/usr/bin/env bash`). `run-all.sh` checks each one with `sh -n` or `bash -n` to
  match, and fails a `.sh` file without one. Tests are mode 644 and run as
  `bash <file>`. `npm run test:scripts` runs the whole suite locally, and CI runs the
  same file on Ubuntu, where `sh` is dash, as it is in the backend image.
```

### ai/project.md: structure and commands

Lines 44-45, the `scripts/` entry, become:

```markdown
- `scripts/` - local tooling (ports, worktrees) and server provisioning, deployment,
  TLS, and backup scripts; `scripts/tests/` holds the shell-script tests and
  `run-all.sh`, which checks every script's syntax and then runs them
```

After line 56 (`npm run test:front`), add:

```markdown
- `npm run test:scripts` - `bash -n` or `sh -n` on every shell script by its shebang,
  then `scripts/tests/test-*.sh`, through `scripts/tests/run-all.sh`, which CI runs too
```

### README.md: commands table and layout

After line 138 (`npm run test:back`), add a row. Its cells are 25 and 47 characters
wide, the table's own widths, so Prettier leaves the other rows alone:

```markdown
| `npm run test:scripts`    | Shell script syntax checks and `scripts/tests/` |
```

After line 184 (`├── scripts/ ...`), add:

```text
│   └── tests/         # Shell script tests (npm run test:scripts)
```

### tools.md: CI and ShellCheck entries, and a shell-script section

Lines 232-237, the GitHub Actions entry, become:

```markdown
- **GitHub Actions**: CI, in `.github/workflows/ci.yml`, on every push and pull
  request, and on demand from the Actions tab. Its five jobs cover the backend (Ruff,
  pydoclint, the function-length check, basedpyright, and pytest against a PostgreSQL
  service), the fallow audit against the base branch, the frontend (ESLint, Prettier,
  markdownlint, and Vitest), the production build, and the shell scripts (syntax checks
  and `scripts/tests/`). `assign-issues.yml` assigns each new issue to the repository
  owner through `actions/github-script`.
```

Lines 315-317, the ShellCheck entry, become:

```markdown
- **ShellCheck**: runs in the editor through its extension; two scripts carry
  `# shellcheck` directives where its warnings do not apply. CI does not run it; its
  shell-script job checks syntax with `bash -n` and `sh -n` and runs `scripts/tests/`.
```

Between line 202 (the end of "Frontend build, test, and quality tools") and
`## Containers and images` (line 204), insert:

```markdown
## Shell script tests

`npm run test:scripts` runs `scripts/tests/run-all.sh`, and so does CI.

- **`scripts/tests/`**: Bash tests. Each `test-<script>.sh` runs its script against
  stub commands such as `docker`, `lsof`, and `rclone`, which log their calls instead
  of acting, and checks the log and the files the script wrote;
  `test-compose-config.sh` checks the rendered Compose stacks instead. `run-all.sh`
  first checks every script's syntax with `bash -n` or `sh -n`, as its shebang names.
- **jq**: `test-compose-config.sh` queries the JSON that `docker compose config`
  renders for each stack with it. The CI runner has it; locally, the test skips
  without it or without the docker CLI.
```

## Parallelism

Can be done in parallel (no file is shared between groups):

- A: `scripts/tests/run-all.sh`, `package.json`, `.github/workflows/ci.yml`
- B: `scripts/tests/test-up.sh`, `scripts/tests/test-entrypoint.sh`
- C: `scripts/tests/test-compose-config.sh`, `scripts/tests/test-backup.sh`
- D: `ai/conventions.md`, `ai/project.md`, `README.md`, `tools.md`

Each test can run on its own as soon as it is written (`bash scripts/tests/test-up.sh`;
`test-backup.sh` through the container command in its header).

Must be sequential, after A to D: verification steps 1 to 4 below. `run-all.sh` needs
every test in place, and the deliberate breakages run one at a time, each reverted
before the next. Steps 5 to 7 follow them.

## No other changes needed

- No script under test changes: the tests pin today's `up.sh`, `entrypoint.sh`,
  `backup.sh`, and Compose files.
- `.claude/settings.json` already allows `npm run *`.
- Python tooling ignores the new files: `scripts/check_function_length.py` scans only
  `*.py` (lines 76-79), and Ruff, pydoclint, and basedpyright see only Python. Prettier
  formats no shell, so `.prettierignore` stays as it is. lint-staged gets no shell rule.
- `.husky/pre-commit` and `.husky/pre-push` carry `#!/bin/sh`, so `run-all.sh`
  syntax-checks them without any change.
- Hukilau's watch, Flask dev server, LAN stack, `DEVELOPMENT_PACKAGES`,
  `APP_ENVIRONMENT`, and local-daily-backup cases are not ported, because the template
  lacks those behaviours. #13 (compose watch) adds the watch cases to `test-up.sh` and
  the development branch to `test-entrypoint.sh`; #14 (local daily backups) adds the
  local-daily cases to `test-backup.sh`.
- `workflow_dispatch` can be triggered only once the workflow is on the default
  branch, so it is checked after the merge.

## Verification

1. `npm run test:scripts` on the Mac prints `Checked the syntax of 22 scripts.` (17
   today plus the 5 new files). It then prints `PASS` for `test-compose-config.sh`,
   `test-entrypoint.sh`, and `test-up.sh`, and `SKIP` for `test-backup.sh` after its
   Linux message, and exits 0.
2. `CI=true npm run test:scripts` fails on `test-backup.sh` with
   `skipped itself, and CI runs every test`, proving CI cannot skip a test.
3. With Docker running, `docker run --rm -v "$PWD:/repo" -w /repo debian:trixie bash
   scripts/tests/test-backup.sh` prints `Backup regression checks passed.`
4. Deliberate breakages, one at a time, all in files this change does not touch, so
   `git checkout -- <file>` restores each before the next:
    - Append `if then` to `scripts/down.sh`: `npm run test:scripts` reports
      `FAIL sh -n scripts/down.sh` and exits 1. Append `fi` to `scripts/alert.sh`:
      it reports `FAIL bash -n scripts/alert.sh`.
    - In `docker/docker-compose.prod.yml`, change `'127.0.0.1:${BACKEND_PORT:-5000}:5000'`
      to `'0.0.0.0:${BACKEND_PORT:-5000}:5000'`, then to `'${BACKEND_PORT:-5000}:5000'`.
      Each time, `bash scripts/tests/test-compose-config.sh` prints `The prod
      configuration should have every published port bound to 127.0.0.1.`
    - Delete the `GUNICORN_WORKERS: ${GUNICORN_WORKERS:-4}` line: the test prints
      `should have GUNICORN_WORKERS, 4 by default.`
    - On the host, change `set -Eeuo pipefail` to `set -euo pipefail` in
      `scripts/backup.sh` and rerun step 3's container command: `test-backup.sh` fails
      at the failed-upload case with `Missing /FAILURE: error at line [0-9]+/`.
5. Push. The "Shell scripts" job passes on Ubuntu, and its log shows `PASS` for all
   four tests, `test-backup.sh` included, with no `SKIP`.
6. `npm run lint:md` and `npx prettier --check .` pass.
7. Finally, `npm run test`, `npm run lint`, and `npm run lint:py` in parallel.
