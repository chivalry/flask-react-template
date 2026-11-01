#!/usr/bin/env bash
# Exercise scripts/worktree-doctor.sh against a disposable worktree with a stub
# .venv/bin/python: a healthy worktree, each fatal finding, each warning, and a fatal
# finding that still lets the other checks report. It runs the script with sh, as npm
# does, under macOS's bash 3.2 and on Linux in CI, so it avoids bash 4 features.
set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TEST_DIR=$(mktemp -d)
trap 'rm -rf "$TEST_DIR"' EXIT
export TEST_DIR
WORKTREE="$TEST_DIR/worktree"
COMMANDS="$TEST_DIR/commands"
OUTPUT="$TEST_DIR/output"
MOCK_PYTHON="$TEST_DIR/mock-python"
OPT_HOME=/opt/homebrew/opt/python@3.13/bin
CELLAR_HOME=/opt/homebrew/Cellar/python@3.13/3.13.18/bin

# python logs each call to $TEST_DIR/commands, answers --version, and fails the import
# with a traceback while $TEST_DIR/import-fails exists.
cat > "$MOCK_PYTHON" <<'MOCK'
#!/usr/bin/env bash
set -eu
printf 'python %s\n' "$*" >> "$TEST_DIR/commands"
case "$1" in
  --version) echo 'Python 3.12.7' ;;
  -c)
    if [ -f "$TEST_DIR/import-fails" ]; then
      echo 'Traceback (most recent call last):' >&2
      echo "ModuleNotFoundError: No module named 'flask'" >&2
      exit 1
    fi
    ;;
  *) echo "Unexpected python call: $*" >&2; exit 1 ;;
esac
MOCK
chmod +x "$MOCK_PYTHON"

# A bare `! grep` never fails under set -e, so both checks exit explicitly.
assert_contains() {
  grep -Eq -- "$1" "$2" || { echo "Missing /$1/ in ${2##*/}" >&2; exit 1; }
}

refute_contains() {
  if grep -Eq -- "$1" "$2"; then echo "Unexpected /$1/ in ${2##*/}" >&2; exit 1; fi
}

# set_venv_home DIRECTORY -> pyvenv.cfg as a real venv writes it: home is DIRECTORY, and
# the executable line names the Cellar whatever home says.
set_venv_home() {
  printf 'home = %s\nexecutable = %s\n' "$1" \
    /opt/homebrew/Cellar/python@3.13/3.13.17/bin/python3.13 \
    > "$WORKTREE/.venv/pyvenv.cfg"
}

# make_worktree -> a healthy worktree in place of whatever was there.
make_worktree() {
  rm -rf "$WORKTREE"
  mkdir -p "$WORKTREE/.venv/bin" "$WORKTREE/.vscode" "$WORKTREE/node_modules"
  cp "$MOCK_PYTHON" "$WORKTREE/.venv/bin/python"
  touch "$WORKTREE/.vscode/settings.json"
  set_venv_home "$OPT_HOME"
}

# run_doctor EXPECTED-STATUS -> run the doctor from the worktree root, as npm does, with a
# fresh command log, and check how it exits.
run_doctor() {
  local status=0
  : > "$COMMANDS"
  (cd "$WORKTREE" && sh "$REPO_DIR/scripts/worktree-doctor.sh") > "$OUTPUT" 2>&1 ||
    status=$?
  [ "$status" -eq "$1" ] ||
    { echo "Expected exit $1, not $status. Its output:" >&2
      cat "$OUTPUT" >&2; exit 1; }
}

# A healthy worktree exits 0 with nothing to report, though its pyvenv.cfg names the
# Cellar on the executable line, as a real one does.
make_worktree
run_doctor 0
refute_contains '^(warn|FAIL) ' "$OUTPUT"
assert_contains '^ok    interpreter runs \(Python 3\.12\.7\)$' "$OUTPUT"
assert_contains '^ok    the project imports$' "$OUTPUT"
assert_contains '^ok    venv base survives Homebrew upgrades$' "$OUTPUT"
assert_contains '^ok    VS Code reads \.vscode/settings\.json here$' "$OUTPUT"
assert_contains '^ok    node_modules is present$' "$OUTPUT"
assert_contains "^  .*/worktree/\.venv/bin/python$" "$OUTPUT"
printf '%s\n' 'python --version' 'python -c import src_back.app' | diff -u - "$COMMANDS"

# Without .venv it exits 1, says how to rebuild, and still reports the other checks.
# It reaches no verdict on the import or the base, and leaks no shell error.
rm -rf "$WORKTREE/.venv"
run_doctor 1
assert_contains '^FAIL  no working interpreter at \.venv/bin/python$' "$OUTPUT"
assert_contains 'from a shell with no virtualenv active:$' "$OUTPUT"
assert_contains 'pip install -r requirements-dev\.txt$' "$OUTPUT"
assert_contains '^ok    VS Code reads \.vscode/settings\.json here$' "$OUTPUT"
assert_contains '^ok    node_modules is present$' "$OUTPUT"
assert_contains "^  .*/worktree/\.venv/bin/python$" "$OUTPUT"
refute_contains 'project imports|does not import|venv base|pyvenv' "$OUTPUT"
refute_contains 'No such file|not found' "$OUTPUT"

# The link a deleted base leaves behind fails the same way, and the Cellar warning that
# explains it still appears.
make_worktree
rm "$WORKTREE/.venv/bin/python"
ln -s "$TEST_DIR/deleted/python3.13" "$WORKTREE/.venv/bin/python"
set_venv_home "$CELLAR_HOME"
run_doctor 1
assert_contains '^FAIL  no working interpreter at \.venv/bin/python$' "$OUTPUT"
assert_contains '^warn  venv base is a versioned Homebrew Cellar path$' "$OUTPUT"

# So does an interpreter that is there but cannot start, which a file test would pass.
make_worktree
printf '#!/bin/sh\nexit 1\n' > "$WORKTREE/.venv/bin/python"
run_doctor 1
assert_contains '^FAIL  no working interpreter at \.venv/bin/python$' "$OUTPUT"

# An interpreter that runs but cannot import the project exits 1 and shows the error's
# last line, not the traceback.
make_worktree
touch "$TEST_DIR/import-fails"
run_doctor 1
rm "$TEST_DIR/import-fails"
assert_contains '^FAIL  the project does not import$' "$OUTPUT"
assert_contains "^      ModuleNotFoundError: No module named 'flask'$" "$OUTPUT"
assert_contains 'install with: \.venv/bin/pip install -r requirements-dev\.txt$' "$OUTPUT"
refute_contains 'Traceback' "$OUTPUT"

# Each warning leaves the exit status at 0, and the Cellar one says how to rebuild.
make_worktree
set_venv_home "$CELLAR_HOME"
run_doctor 0
assert_contains '^warn  venv base is a versioned Homebrew Cellar path$' "$OUTPUT"
assert_contains 'rm -rf \.venv && python3 -m venv \.venv$' "$OUTPUT"

make_worktree
rm "$WORKTREE/.vscode/settings.json"
run_doctor 0
assert_contains '^warn  no \.vscode/settings\.json here' "$OUTPUT"

make_worktree
rmdir "$WORKTREE/node_modules"
run_doctor 0
assert_contains '^warn  no node_modules; run npm install$' "$OUTPUT"

# npm run doctor is this script.
assert_contains '"doctor": "sh scripts/worktree-doctor\.sh"' "$REPO_DIR/package.json"

echo 'worktree-doctor.sh regression checks passed.'
