#!/usr/bin/env bash
# Exercise scripts/provision.sh in a disposable clone named my-app, so nothing on the
# machine changes: sudo, dpkg, openssl, and sleep are stubs, sudo only logs what it is
# asked to run, and the commands provision.sh may run only through sudo fail if they run
# without it. It checks the usage error, the generated .env and its secrets, that
# .env.example documents every key the .env sets, the Docker apt source, the sudo calls
# in order, an existing .env left alone, and the reboot after a kernel update. It runs
# under macOS's bash 3.2 and on Linux in CI, so it avoids bash 4 features.
set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TEST_DIR=$(mktemp -d)
trap 'rm -rf "$TEST_DIR"' EXIT
CLONE="$TEST_DIR/my-app"
mkdir -p "$TEST_DIR/bin" "$CLONE/scripts"
# Redirect the two host files provision.sh reads, the OS release and the reboot marker,
# into the disposable test directory.
sed -e "s|/etc/os-release|$TEST_DIR/os-release|g" \
  -e "s|/var/run/reboot-required|$TEST_DIR/reboot-required|g" \
  "$REPO_DIR/scripts/provision.sh" > "$CLONE/scripts/provision.sh"
echo 'VERSION_CODENAME=noble' > "$TEST_DIR/os-release"
export TEST_DIR
export PATH="$TEST_DIR/bin:$PATH"
# usermod gets $USER, and APP_NAME otherwise defaults to the clone's name, so pin the one
# and clear the other.
export USER=tester
unset APP_NAME
ENV_FILE="$CLONE/.env"
COMMANDS="$TEST_DIR/commands"
OUTPUT="$TEST_DIR/output"
# The line continuations in provision.sh's apt source string leave runs of spaces between
# the fields, hence the ` +`.
APT_SOURCE='^deb \[arch=amd64 +signed-by=/etc/apt/keyrings/docker\.asc\] +'
APT_SOURCE+='https://download\.docker\.com/linux/ubuntu +noble stable$'
KEYRING=/etc/apt/keyrings/docker.asc
PACKAGES='ca-certificates curl git vim dnsutils certbot python3-certbot-nginx'
DOCKER_PACKAGES='docker-ce docker-ce-cli containerd.io docker-buildx-plugin'
DOCKER_PACKAGES+=' docker-compose-plugin --fix-missing'

# Every stub is a link to this script. sudo logs its command to $TEST_DIR/commands and
# runs nothing; when it is given tee, it drains stdin, so the pipe cannot SIGPIPE, into
# $TEST_DIR/apt-source. dpkg reports amd64. openssl logs its call and answers
# `rand -hex N` with 2N copies of the digit counting its calls, so the three secrets
# differ and are predictable. sleep only logs. Any other name is a command that
# provision.sh may run only through sudo, so a direct call is logged and fails.
cat > "$TEST_DIR/bin/mock-system" <<'MOCK'
#!/usr/bin/env bash
set -eu
name=${0##*/}
case "$name" in
  sudo)
    printf 'sudo %s\n' "$*" >> "$TEST_DIR/commands"
    if [ "${1:-}" = tee ]; then cat > "$TEST_DIR/apt-source"; fi
    ;;
  dpkg) echo amd64 ;;
  openssl)
    printf 'openssl %s\n' "$*" >> "$TEST_DIR/commands"
    [ "${1:-} ${2:-}" = 'rand -hex' ] ||
      { echo "Unexpected openssl call: $*" >&2; exit 1; }
    count=$(( $(cat "$TEST_DIR/openssl-count" 2>/dev/null || echo 0) + 1 ))
    echo "$count" > "$TEST_DIR/openssl-count"
    printf "%0$(( $3 * 2 ))d\n" 0 | tr 0 "$count"
    ;;
  sleep) printf 'sleep %s\n' "$*" >> "$TEST_DIR/commands" ;;
  *)
    printf '%s ran without sudo: %s\n' "$name" "$*" >> "$TEST_DIR/commands"
    echo "$name ran without sudo: $*" >&2
    exit 1
    ;;
esac
MOCK
chmod +x "$TEST_DIR/bin/mock-system"
# A stub that did not come first on PATH would let provision.sh install packages on this
# machine.
for command in sudo dpkg openssl sleep apt-get curl systemctl usermod reboot; do
  ln -s mock-system "$TEST_DIR/bin/$command"
  [ "$(command -v "$command")" = "$TEST_DIR/bin/$command" ] ||
    { echo "The $command stub does not shadow the real command." >&2; exit 1; }
done

# A bare `! grep` never fails under set -e, so both checks exit explicitly.
assert_contains() {
  grep -Eq -- "$1" "$2" || { echo "Missing /$1/ in ${2##*/}" >&2; exit 1; }
}

refute_contains() {
  if grep -Eq -- "$1" "$2"; then echo "Unexpected /$1/ in ${2##*/}" >&2; exit 1; fi
}

# Start a case from a fresh command log and openssl counter, and with no .env, apt
# source, or reboot marker, so no case sees another's files.
start_test_case() {
  rm -f "$ENV_FILE" "$TEST_DIR/apt-source" "$TEST_DIR/openssl-count" \
    "$TEST_DIR/reboot-required"
  : > "$COMMANDS"
}

# run_provision [NAME=value...] -> run the copy's provision.sh for example.com from the
# clone with the given variables set, and show its output if it fails. A direct call to
# a command that needs sudo fails the run even if provision.sh were to ignore the stub's
# failure.
run_provision() {
  (cd "$CLONE" && env "$@" bash scripts/provision.sh example.com) > "$OUTPUT" 2>&1 ||
    { echo 'provision.sh example.com failed:' >&2; cat "$OUTPUT" >&2; exit 1; }
  refute_contains 'ran without sudo' "$COMMANDS"
}

# expect_calls PATTERN LINE... -> the logged calls that match PATTERN are exactly these
# lines, in this order.
expect_calls() {
  local pattern=$1
  shift
  grep -E "$pattern" "$COMMANDS" > "$TEST_DIR/matching-calls" || true
  printf '%s\n' "$@" | diff -u - "$TEST_DIR/matching-calls"
}

# The rewrite must leave provision.sh no host path to read: a real /etc/os-release or
# reboot marker would let the machine decide the test. $TEST_DIR comes out first because
# on macOS it begins with /var/folders/.
sed "s|$TEST_DIR||g" "$CLONE/scripts/provision.sh" \
  > "$TEST_DIR/provision-without-test-dir"
refute_contains '/etc/os-release|/var/run/reboot-required' \
  "$TEST_DIR/provision-without-test-dir"

# Without a domain, provision.sh stops at its usage message before it runs anything.
start_test_case
if (cd "$CLONE" && bash scripts/provision.sh) > "$OUTPUT" 2> "$TEST_DIR/stderr"; then
  echo 'Expected provision.sh without a domain to fail.' >&2
  exit 1
fi
assert_contains 'usage: bash scripts/provision\.sh <domain>' "$TEST_DIR/stderr"
[ ! -s "$COMMANDS" ] ||
  { echo 'provision.sh ran commands without a domain:' >&2; cat "$COMMANDS" >&2; exit 1; }

# A fresh server gets a mode 600 .env with the clone's name, the domain, the three
# generated secrets, and every retention setting, and the Docker apt source for its
# release.
start_test_case
run_provision
[ "$(find "$ENV_FILE" -perm 600)" = "$ENV_FILE" ] ||
  { echo '.env is not mode 600.' >&2; exit 1; }
assert_contains '^APP_NAME=my-app$' "$ENV_FILE"
assert_contains '^COMPOSE_PROJECT_NAME=my-app$' "$ENV_FILE"
assert_contains '^DOMAIN=example\.com$' "$ENV_FILE"
assert_contains '^PUBLIC_BASE_URL=https://example\.com$' "$ENV_FILE"
assert_contains '^SPACES_BUCKET=$' "$ENV_FILE"
assert_contains '^RETAIN_DAILY=14$' "$ENV_FILE"
assert_contains '^RETAIN_WEEKLY=8$' "$ENV_FILE"
assert_contains '^RETAIN_MONTHLY=6$' "$ENV_FILE"
assert_contains '^RETAIN_LOCAL_DAILY=7$' "$ENV_FILE"
# The heredoc is unquoted, so the backups comment names the real directory.
assert_contains '^# /var/backups/my-app/daily\. ' "$ENV_FILE"
assert_contains '^POSTGRES_PASSWORD=1{32}$' "$ENV_FILE"
assert_contains '^DATABASE_URL=postgresql://app:1{32}@db:5432/app$' "$ENV_FILE"
assert_contains '^SECRET_KEY=2{64}$' "$ENV_FILE"
assert_contains '^ADMIN_PASSWORD=3{32}$' "$ENV_FILE"
# Every key the .env sets is one .env.example documents, which catches a variable added
# to one file but not the other. The first check keeps the loop from passing on an
# empty list.
sed -n 's/^\([A-Z_][A-Z0-9_]*\)=.*/\1/p' "$ENV_FILE" > "$TEST_DIR/generated-keys"
assert_contains '^APP_NAME$' "$TEST_DIR/generated-keys"
while IFS= read -r key; do
  grep -Eq "^$key=" "$REPO_DIR/.env.example" ||
    { echo "provision.sh sets $key, which .env.example lacks." >&2; exit 1; }
done < "$TEST_DIR/generated-keys"
assert_contains "$APT_SOURCE" "$TEST_DIR/apt-source"
expect_calls '^sudo ' \
  'sudo apt-get update -qq' \
  'sudo apt-get upgrade -y -qq' \
  "sudo apt-get install -y -qq $PACKAGES" \
  'sudo install -m 0755 -d /etc/apt/keyrings' \
  "sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o $KEYRING" \
  "sudo chmod a+r $KEYRING" \
  'sudo tee /etc/apt/sources.list.d/docker.list' \
  'sudo apt-get update -qq' \
  "sudo apt-get install -y $DOCKER_PACKAGES" \
  'sudo usermod -aG docker tester' \
  'sudo rm -f /etc/nginx/sites-enabled/default' \
  'sudo systemctl enable nginx' \
  'sudo systemctl start nginx'
refute_contains '^sudo reboot$' "$COMMANDS"
assert_contains 'Log out and back in' "$OUTPUT"

# APP_NAME in the environment replaces the clone's name.
start_test_case
run_provision APP_NAME=custom
assert_contains '^APP_NAME=custom$' "$ENV_FILE"
assert_contains '^COMPOSE_PROJECT_NAME=custom$' "$ENV_FILE"

# An existing .env is never overwritten, and no secret is generated for it.
start_test_case
echo 'SECRET_KEY=generated-on-an-earlier-run' > "$ENV_FILE"
cp "$ENV_FILE" "$TEST_DIR/before.env"
run_provision
cmp -s "$TEST_DIR/before.env" "$ENV_FILE" ||
  { echo 'provision.sh rewrote an existing .env.' >&2; exit 1; }
assert_contains 'already exists' "$OUTPUT"
refute_contains '^openssl ' "$COMMANDS"

# A kernel update leaves the reboot marker, and provision.sh then waits five seconds
# and reboots, in that order.
start_test_case
touch "$TEST_DIR/reboot-required"
run_provision
expect_calls '^(sleep |sudo reboot$)' 'sleep 5' 'sudo reboot'
assert_contains 'rebooting in 5 seconds' "$OUTPUT"

echo 'Provision regression checks passed.'
