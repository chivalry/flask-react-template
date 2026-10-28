#!/usr/bin/env bash
# Exercise scripts/remote-deploy.sh: the real script runs in a disposable copy of the
# repository, with a stub ssh command that logs its arguments. It checks the command each
# environment sends to the server, where the host and the clone's name come from, which
# environment names it accepts, and each way it stops before it runs ssh. It runs under
# macOS's bash 3.2 and on Linux in CI, so it avoids bash 4 features.
set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TEST_DIR=$(mktemp -d)
trap 'rm -rf "$TEST_DIR"' EXIT
mkdir -p "$TEST_DIR/bin" "$TEST_DIR/repo/scripts"
cp "$REPO_DIR/scripts/remote-deploy.sh" "$TEST_DIR/repo/scripts/remote-deploy.sh"
export TEST_DIR
export PATH="$TEST_DIR/bin:$PATH"
ENV_FILE="$TEST_DIR/repo/.env"
EXAMPLE_FILE="$TEST_DIR/repo/.env.example"
COMMANDS="$TEST_DIR/commands"
OUTPUT="$TEST_DIR/output"
USAGE='usage: bash scripts/remote-deploy.sh [--environment <name>] [<host>]'
# A DEPLOY_HOST in the developer's shell must not decide a case.
unset DEPLOY_HOST

# The script sends its one remote command as a single argument, so the log shows it
# exactly as the remote shell receives it, the ~ included.
cat > "$TEST_DIR/bin/ssh" <<'MOCK'
#!/usr/bin/env bash
set -eu
printf 'ssh %s\n' "$*" >> "$TEST_DIR/commands"
MOCK
chmod +x "$TEST_DIR/bin/ssh"
# A stub that did not come first on PATH would let the script reach a real server.
[ "$(command -v ssh)" = "$TEST_DIR/bin/ssh" ] ||
  { echo 'The ssh stub does not shadow the real command.' >&2; exit 1; }

# A bare `! grep` never fails under set -e, so both checks exit explicitly.
assert_contains() {
  grep -Eq -- "$1" "$2" || { echo "Missing /$1/ in ${2##*/}" >&2; exit 1; }
}

# assert_line FILE LINE -> LINE is a whole line of FILE, compared as a fixed string.
assert_line() {
  grep -qxF -- "$2" "$1" || { echo "Missing the line '$2' in ${1##*/}" >&2; exit 1; }
}

# write_env_files -> the local .env names the app myapp, and .env.example from-example.
write_env_files() {
  echo 'APP_NAME=myapp' > "$ENV_FILE"
  echo 'APP_NAME=from-example' > "$EXAMPLE_FILE"
}

# run_remote_deploy [ARG...] -> run the copy of remote-deploy.sh with a fresh command log
# and leave its output in $OUTPUT; the status is the script's. DEPLOY_HOST comes from
# the caller, as `DEPLOY_HOST=host run_remote_deploy` sets it.
run_remote_deploy() {
  : > "$COMMANDS"
  bash "$TEST_DIR/repo/scripts/remote-deploy.sh" "$@" > "$OUTPUT" 2>&1
}

# run_deploy [ARG...] -> the run succeeds; show its output if it fails.
run_deploy() {
  run_remote_deploy "$@" ||
    { echo 'remote-deploy.sh failed. Its output:' >&2; cat "$OUTPUT" >&2; exit 1; }
}

# expect_failure DESCRIPTION [ARG...] -> the run exits 1, as every refusal does.
expect_failure() {
  local status=0 description=$1
  shift
  run_remote_deploy "$@" || status=$?
  [ "$status" -eq 1 ] || {
    echo "Expected $description; remote-deploy.sh exited $status. Its output:" >&2
    cat "$OUTPUT" >&2
    exit 1
  }
}

# expect_calls LINE... -> the stub ran exactly these lines, in this order.
expect_calls() {
  printf '%s\n' "$@" | diff -u - "$COMMANDS"
}

# assert_no_commands -> the ssh stub never ran.
assert_no_commands() {
  [ ! -s "$COMMANDS" ] ||
    { echo 'Unexpected commands:' >&2; cat "$COMMANDS" >&2; exit 1; }
}

write_env_files

# With no argument, the host comes from DEPLOY_HOST and the environment is production,
# whose clone is ~/<APP_NAME>.
DEPLOY_HOST=root@example.com run_deploy
expect_calls \
  'ssh root@example.com bash ~/myapp/scripts/deploy.sh --environment production'

# Another environment's clone is ~/<APP_NAME>-<environment>, and deploy.sh is told which
# environment to deploy.
DEPLOY_HOST=root@example.com run_deploy --environment staging
expect_calls \
  'ssh root@example.com bash ~/myapp-staging/scripts/deploy.sh --environment staging'

# A host on the command line wins over DEPLOY_HOST, before or after the option, and the
# option takes its value after a space or an equals sign.
STAGING_CALL='ssh other-host bash ~/myapp-staging/scripts/deploy.sh --environment staging'
DEPLOY_HOST=root@example.com run_deploy --environment=staging other-host
expect_calls "$STAGING_CALL"
DEPLOY_HOST=root@example.com run_deploy other-host --environment staging
expect_calls "$STAGING_CALL"

# Without a host argument or DEPLOY_HOST the run stops before ssh. The explicit check
# replaces ${DEPLOY_HOST:?}, which exits 127 under bash 3.2.
expect_failure 'a missing host to stop the run'
assert_contains 'set DEPLOY_HOST or pass a host' "$OUTPUT"
assert_no_commands

# A .env without APP_NAME falls back to .env.example's. With neither file setting it, the
# run stops before ssh.
echo 'DOMAIN=example.com' > "$ENV_FILE"
DEPLOY_HOST=root@example.com run_deploy
expect_calls \
  'ssh root@example.com bash ~/from-example/scripts/deploy.sh --environment production'
echo 'DOMAIN=example.com' > "$EXAMPLE_FILE"
DEPLOY_HOST=root@example.com expect_failure 'a missing APP_NAME to stop the run'
assert_contains 'APP_NAME is not set' "$OUTPUT"
assert_no_commands
write_env_files

# The environment name becomes part of a path and of the remote command line, so only
# lowercase letters, digits, and hyphens pass. An unknown option and a second host fail
# the same way. DEPLOY_HOST is set, so only the usage error can stop these runs.
export DEPLOY_HOST=root@example.com
expect_failure 'an uppercase environment name to stop the run' --environment Staging
assert_line "$OUTPUT" "$USAGE"
assert_no_commands
expect_failure 'a shell metacharacter in the environment name to stop the run' \
  --environment 'a;b'
assert_line "$OUTPUT" "$USAGE"
assert_no_commands
expect_failure 'an unknown option to stop the run' --bogus
assert_line "$OUTPUT" "$USAGE"
assert_no_commands
expect_failure 'a second host to stop the run' first-host second-host
assert_line "$OUTPUT" "$USAGE"
assert_no_commands
unset DEPLOY_HOST

echo 'remote-deploy.sh regression checks passed.'
