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
