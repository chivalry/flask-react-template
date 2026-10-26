#!/usr/bin/env bash
# Exercise docker/entrypoint.sh's development and production paths with stub flask,
# python, and gunicorn commands. It runs under macOS's bash 3.2 and on Linux in CI, so
# it avoids bash 4 features; CI's sh is dash, as the backend image's is.
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
FLASK_SERVER='flask --app src_back.app run --host 0.0.0.0 --port 5000'
FLASK_SERVER="$FLASK_SERVER --reload --no-debugger"

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

# Development migrates, seeds, and then runs Flask's reloader with the debugger off.
run_entrypoint FLASK_ENV=development
expect_calls "$MIGRATE" "$SEED" "$FLASK_SERVER"

# Every other stack, including one that never sets FLASK_ENV, migrates, seeds, and then
# runs gunicorn, with two workers unless GUNICORN_WORKERS, which the production override
# sets, says otherwise.
run_entrypoint
expect_calls "$MIGRATE" "$SEED" "$GUNICORN"
run_entrypoint FLASK_ENV=production
expect_calls "$MIGRATE" "$SEED" "$GUNICORN"
run_entrypoint FLASK_ENV=production GUNICORN_WORKERS=4
expect_calls "$MIGRATE" "$SEED" "${GUNICORN/--workers 2/--workers 4}"

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

echo 'Entrypoint regression checks passed.'
