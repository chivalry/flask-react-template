#!/usr/bin/env bash
# Exercise .devcontainer/install-vscode-extensions.sh in a disposable repository, under a
# disposable HOME that holds stub VS Code servers: which server it picks, what it asks
# that server to install, and when its marker skips the install. It exits 77 without
# python3, which the script parses with. It runs under macOS's bash 3.2 and on Linux in
# CI, so it avoids bash 4 features.
set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
command -v python3 > /dev/null ||
  { echo 'test-install-vscode-extensions.sh needs python3.' >&2; exit 77; }
TEST_DIR=$(mktemp -d)
trap 'rm -rf "$TEST_DIR"' EXIT
export TEST_DIR
# The space proves the script quotes every path that starts from HOME.
export HOME="$TEST_DIR/ho me"
REPOSITORY="$TEST_DIR/repository"
mkdir -p "$HOME" "$REPOSITORY/.devcontainer" "$REPOSITORY/.vscode"
cp "$REPO_DIR/.devcontainer/install-vscode-extensions.sh" "$REPOSITORY/.devcontainer/"
RECOMMENDATIONS="$REPOSITORY/.vscode/extensions.json"
SERVER_DIR="$HOME/.vscode-server"
MARKER="$SERVER_DIR/data/Machine/.recommended-extensions.sha256"
COMMANDS="$TEST_DIR/commands"
OUTPUT="$TEST_DIR/output"
DATA_DIRECTORY="--server-data-dir $SERVER_DIR"

# A bare `! grep` never fails under set -e, so both checks exit explicitly.
assert_contains() {
  grep -Eq -- "$1" "$2" || { echo "Missing /$1/ in ${2##*/}" >&2; exit 1; }
}

refute_contains() {
  if grep -Eq -- "$1" "$2"; then echo "Unexpected /$1/ in ${2##*/}" >&2; exit 1; fi
}

# expect_call LINE -> the servers ran exactly this one line.
expect_call() {
  printf '%s\n' "$1" | diff -u - "$COMMANDS"
}

# expect_no_calls -> no server ran.
expect_no_calls() {
  [ ! -s "$COMMANDS" ] || { echo 'A server ran:' >&2; cat "$COMMANDS" >&2; exit 1; }
}

# expect_no_marker -> nothing recorded an install.
expect_no_marker() {
  [ ! -e "$MARKER" ] || { echo 'A marker exists.' >&2; exit 1; }
}

# expect_marker SHA -> the marker still holds SHA.
expect_marker() {
  [ "$(cat "$MARKER")" = "$1" ] || { echo 'The marker changed.' >&2; exit 1; }
}

# add_server COMMIT STAMP -> a stub code-server for COMMIT, modified at the touch -t
# STAMP. It logs an install and fails it while $TEST_DIR/install-fails exists. Otherwise
# the install leaves $TEST_DIR/listed as what it lists next, in capitals, because the real
# list keeps each publisher's letter case, so a list before the install finds nothing.
add_server() {
  local server="$SERVER_DIR/bin/$1/bin/code-server"
  mkdir -p "${server%/*}"
  cat > "$server" <<MOCK
#!/usr/bin/env bash
set -eu
if [ "\$*" = '--server-data-dir $SERVER_DIR --list-extensions' ]; then
  tr 'a-z' 'A-Z' < "\$TEST_DIR/installed"
  exit 0
fi
printf '%s\n' "$1 \$*" >> "\$TEST_DIR/commands"
[ ! -f "\$TEST_DIR/install-fails" ]
cp "\$TEST_DIR/listed" "\$TEST_DIR/installed"
MOCK
  chmod +x "$server"
  touch -t "$2" "$server"
}

# recommend ID... -> write a recommendations file holding these ids, plus an unwanted id
# that must never install, and have the servers list every id.
recommend() {
  local ids
  ids=$(printf '"%s",' "$@")
  printf '{"recommendations": [%s], "unwantedRecommendations": ["no.thanks"]}\n' \
    "${ids%,}" > "$RECOMMENDATIONS"
  printf '%s\n' "$@" > "$TEST_DIR/listed"
}

# attach [EXPECTED-STATUS] -> run the script as postAttachCommand does, from the
# repository root with a relative path, and check how it exits.
attach() {
  local expected=${1:-0} status=0
  : > "$COMMANDS"
  (cd "$REPOSITORY" && sh .devcontainer/install-vscode-extensions.sh) > "$OUTPUT" 2>&1 ||
    status=$?
  [ "$status" -eq "$expected" ] ||
    { echo "Expected exit $expected, not $status. Its output:" >&2
      cat "$OUTPUT" >&2; exit 1; }
}

# With no server under HOME there is nothing to install with, which is not a failure, and
# no marker, so the next attach tries again.
recommend one.first two.second
attach
assert_contains '^No VS Code server under ' "$OUTPUT"
expect_no_marker

# The first attach installs each recommendation in one call and records the file's
# sha256. It leaves out the host-only extensions and the unwanted id, and it creates the
# marker's directory.
add_server aaaa-older 202601010000
recommend one.first ms-vscode-remote.remote-containers \
  ms-vscode-remote.remote-ssh two.second
attach
expect_call "aaaa-older $DATA_DIRECTORY --install-extension one.first \
--install-extension two.second"
assert_contains '^[0-9a-f]{64}$' "$MARKER"

# A second attach installs nothing and prints nothing.
attach
expect_no_calls
[ ! -s "$OUTPUT" ] ||
  { echo 'An up-to-date attach printed:' >&2; cat "$OUTPUT" >&2; exit 1; }

# Any change to the file installs again, even one that leaves the same ids, through the
# newest server, which sorts neither first nor last by name.
add_server mmmm-newest 202606010000
add_server zzzz-middle 202603010000
printf ' \n' >> "$RECOMMENDATIONS"
attach
expect_call "mmmm-newest $DATA_DIRECTORY --install-extension one.first \
--install-extension two.second"
recommend one.first four.fourth
attach
expect_call "mmmm-newest $DATA_DIRECTORY --install-extension one.first \
--install-extension four.fourth"
attach
expect_no_calls

# A failed install exits with the server's status and keeps the old marker, so the next
# attach installs again, even when the server already lists every id.
MARKER_BEFORE=$(cat "$MARKER")
recommend five.fifth
cp "$TEST_DIR/listed" "$TEST_DIR/installed"
touch "$TEST_DIR/install-fails"
attach 1
expect_marker "$MARKER_BEFORE"
rm "$TEST_DIR/install-fails"
attach
expect_call "mmmm-newest $DATA_DIRECTORY --install-extension five.fifth"

# An install that exits 0 but leaves an id off the server's list fails the same way, by
# name, so a write lost to the server's own installs is retried. Every id counts, a longer
# id does not stand in for it, and letter case does not count as a loss, because the
# stub lists in capitals.
MARKER_BEFORE=$(cat "$MARKER")
recommend six.sixth seven.seventh eight.eighth
printf '%s\n' six.sixth seven.seventh-pack eight.eighth > "$TEST_DIR/listed"
attach 1
assert_contains '^ERROR: seven\.seventh is not installed' "$OUTPUT"
expect_marker "$MARKER_BEFORE"
recommend six.sixth seven.seventh eight.eighth
attach
[ "$(cat "$MARKER")" != "$MARKER_BEFORE" ] ||
  { echo 'The retry wrote no marker.' >&2; exit 1; }

# A file that does not parse stops the script: no install, and no new marker.
MARKER_BEFORE=$(cat "$MARKER")
printf 'not json\n' > "$RECOMMENDATIONS"
attach 1
expect_no_calls
expect_marker "$MARKER_BEFORE"

# A file with nothing to install calls no server, because a call with no ids would start
# one, and records the file so the next attach does not parse it for nothing. That holds
# for a list of only host-side ids and for a file with no list at all.
rm "$MARKER"
recommend ms-vscode-remote.remote-containers
attach
expect_no_calls
assert_contains '^[0-9a-f]{64}$' "$MARKER"
rm "$MARKER"
printf '{}\n' > "$RECOMMENDATIONS"
attach
expect_no_calls
assert_contains '^[0-9a-f]{64}$' "$MARKER"

# Without the file there is nothing to do, which is not a failure.
rm "$RECOMMENDATIONS"
attach
assert_contains '^No .*extensions\.json, so no extensions to install\.$' "$OUTPUT"
expect_no_calls

# The repository's own file parses, and installs the one recommendation that
# customizations.vscode.extensions lacks, plus another Microsoft id, so the host-only
# filter stays narrow. postAttachCommand runs this script, and the container can build:
# docker-in-docker refuses Moby on the image's Debian release.
cp "$REPO_DIR/.vscode/extensions.json" "$RECOMMENDATIONS"
python3 - "$RECOMMENDATIONS" > "$TEST_DIR/listed" <<'PYTHON'
import json
import sys

with open(sys.argv[1], encoding='utf-8') as handle:
    print('\n'.join(json.load(handle)['recommendations']))
PYTHON
attach
assert_contains ' --install-extension vitest\.explorer( |$)' "$COMMANDS"
assert_contains ' --install-extension ms-python\.python( |$)' "$COMMANDS"
refute_contains 'ms-vscode-remote' "$COMMANDS"
DEVCONTAINER="$REPO_DIR/.devcontainer/devcontainer.json"
assert_contains '"postAttachCommand": "sh \.devcontainer/install-vscode-extensions\.sh"' \
  "$DEVCONTAINER"
assert_contains '"moby": false' "$DEVCONTAINER"

echo 'install-vscode-extensions.sh regression checks passed.'
