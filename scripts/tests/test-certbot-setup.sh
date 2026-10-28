#!/usr/bin/env bash
# Exercise scripts/certbot-setup.sh: the real script runs in a disposable copy of the
# repository, with its /etc paths redirected into the test directory and stub sudo,
# systemctl, certbot, dig, and curl commands. It checks that a bare host gets the
# standalone authenticator, with nginx stopped and started again and the renewal config
# switched to nginx; that a host whose nginx already serves a site gets the nginx
# authenticator with nothing stopped; that whatever was stopped starts again when certbot
# fails; and each way the script stops before certbot. It runs under macOS's bash 3.2 and
# on Linux in CI, so it avoids bash 4 features.
set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TEST_DIR=$(mktemp -d)
trap 'rm -rf "$TEST_DIR"' EXIT
mkdir -p "$TEST_DIR/bin" "$TEST_DIR/repo/scripts"
export TEST_DIR
export PATH="$TEST_DIR/bin:$PATH"
FLAGS="$TEST_DIR/flags"
ENV_FILE="$TEST_DIR/repo/.env"
COMMANDS="$TEST_DIR/commands"
OUTPUT="$TEST_DIR/output"
LETSENCRYPT_DIR="$TEST_DIR/letsencrypt"
NGINX_DIR="$TEST_DIR/nginx"
RENEWAL_CONF="$LETSENCRYPT_DIR/renewal/example.com.conf"

# A bare `! grep` never fails under set -e, so both checks exit explicitly.
assert_contains() {
  grep -Eq -- "$1" "$2" || { echo "Missing /$1/ in ${2##*/}" >&2; exit 1; }
}

refute_contains() {
  if grep -Eq -- "$1" "$2"; then echo "Unexpected /$1/ in ${2##*/}" >&2; exit 1; fi
}

# assert_line FILE LINE -> LINE is a whole line of FILE, compared as a fixed string.
assert_line() {
  grep -qxF -- "$2" "$1" || { echo "Missing the line '$2' in ${1##*/}" >&2; exit 1; }
}

# Redirect the host's certificate and nginx directories into the test directory.
sed -e "s|/etc/letsencrypt|$LETSENCRYPT_DIR|g" -e "s|/etc/nginx|$NGINX_DIR|g" \
  "$REPO_DIR/scripts/certbot-setup.sh" > "$TEST_DIR/repo/scripts/certbot-setup.sh"
# A host path the rewrite missed would send the script to the real /etc, so none may be
# left; $TEST_DIR is cut out first, so only text the rewrite left alone is checked.
sed "s|$TEST_DIR||g" "$TEST_DIR/repo/scripts/certbot-setup.sh" \
  > "$TEST_DIR/rewritten-certbot-setup.sh"
refute_contains '/etc/' "$TEST_DIR/rewritten-certbot-setup.sh"

# Each stub logs its call to $TEST_DIR/commands before it answers, so a refused call is
# logged too, and reads its conditions from markers in $TEST_DIR/flags. systemctl
# reports a service active while active-<name> exists, and stop and start remove and
# create that marker; certbot fails while certbot-fails exists, and otherwise writes the
# renewal config with the authenticator its flag names, as the real one does; dig
# resolves the domain to 203.0.113.10, which curl reports as this machine's address
# unless other-ip exists.
cat > "$TEST_DIR/bin/mock-command" <<'MOCK'
#!/usr/bin/env bash
set -eu
name=${0##*/}
flags="$TEST_DIR/flags"
printf '%s\n' "$name $*" >> "$TEST_DIR/commands"
case "$name" in
  systemctl)
    case "$1" in
      is-active) [ -f "$flags/active-$3" ] ;;
      stop) rm -f "$flags/active-$2" ;;
      start) touch "$flags/active-$2" ;;
      *) echo "Unexpected systemctl call: $*" >&2; exit 1 ;;
    esac
    ;;
  certbot)
    [ ! -f "$flags/certbot-fails" ] || exit 1
    case "$*" in
      'certonly --standalone -d '*) authenticator=standalone ;;
      'certonly --nginx -d '*) authenticator=nginx ;;
      *) echo "Unexpected certbot call: $*" >&2; exit 1 ;;
    esac
    mkdir -p "$TEST_DIR/letsencrypt/renewal"
    echo "authenticator = $authenticator" > "$TEST_DIR/letsencrypt/renewal/$4.conf"
    ;;
  dig) echo 203.0.113.10 ;;
  curl) if [ -f "$flags/other-ip" ]; then echo 198.51.100.1; else echo 203.0.113.10; fi ;;
  *) echo "Unexpected mock command: $name" >&2; exit 1 ;;
esac
MOCK
chmod +x "$TEST_DIR/bin/mock-command"
# sudo is a script of its own, so the call lists below hold only the commands it runs.
# It runs its arguments, except that BSD sed -i needs a suffix, so the in-place edit
# becomes a copy and a move.
cat > "$TEST_DIR/bin/sudo" <<'SUDO'
#!/usr/bin/env bash
set -eu
if [ "$1" = sed ] && [ "$2" = -i ]; then
  sed "$3" "$4" > "$4.tmp"
  mv "$4.tmp" "$4"
else
  "$@"
fi
SUDO
chmod +x "$TEST_DIR/bin/sudo"
# A stub that did not come first on PATH would let the script reach the real certbot,
# systemd, or the public internet.
for command in systemctl certbot dig curl; do
  ln -s mock-command "$TEST_DIR/bin/$command"
done
for command in sudo systemctl certbot dig curl; do
  [ "$(command -v "$command")" = "$TEST_DIR/bin/$command" ] ||
    { echo "The $command stub does not shadow the real command." >&2; exit 1; }
done

STANDALONE='certbot certonly --standalone -d example.com'
STANDALONE+=' --non-interactive --agree-tos -m you@example.com'
NGINX_AUTHENTICATOR='certbot certonly --nginx -d example.com'
NGINX_AUTHENTICATOR+=' --non-interactive --agree-tos -m you@example.com'

# start_test_case [LINE...] -> a fresh start: nginx running with no enabled site, no
# renewal config, no flags, an empty command log, and a .env holding the domain and the
# email plus any given lines, which win because certbot-setup.sh reads the last one.
start_test_case() {
  rm -rf "$LETSENCRYPT_DIR" "$NGINX_DIR" "$FLAGS"
  mkdir -p "$NGINX_DIR/sites-enabled" "$FLAGS"
  touch "$FLAGS/active-nginx"
  : > "$COMMANDS"
  printf '%s\n' DOMAIN=example.com CERTBOT_EMAIL=you@example.com "$@" > "$ENV_FILE"
}

# add_enabled_site -> nginx serves a site, as on a host that already runs production.
add_enabled_site() {
  touch "$NGINX_DIR/sites-enabled/myapp"
}

# run_certbot_setup [ARG...] -> run the copy of certbot-setup.sh and leave its output in
# $OUTPUT; the status is the script's.
run_certbot_setup() {
  bash "$TEST_DIR/repo/scripts/certbot-setup.sh" "$@" > "$OUTPUT" 2>&1
}

# run_setup -> the run succeeds; show its output if it fails.
run_setup() {
  run_certbot_setup ||
    { echo 'certbot-setup.sh failed. Its output:' >&2; cat "$OUTPUT" >&2; exit 1; }
}

# expect_failure DESCRIPTION -> the run exits 1, as every stop of the script does,
# certbot's failure included.
expect_failure() {
  local status=0
  run_certbot_setup || status=$?
  [ "$status" -eq 1 ] || {
    echo "Expected $1 (exit status 1), got $status. Its output:" >&2
    cat "$OUTPUT" >&2
    exit 1
  }
}

# expect_calls LINE... -> the stubs ran exactly these lines, in this order.
expect_calls() {
  printf '%s\n' "$@" | diff -u - "$COMMANDS"
}

# assert_no_commands -> no stub ran.
assert_no_commands() {
  [ ! -s "$COMMANDS" ] ||
    { echo 'Unexpected commands:' >&2; cat "$COMMANDS" >&2; exit 1; }
}

# assert_last_command LINE -> the last command logged is LINE.
assert_last_command() {
  [ "$(tail -n 1 "$COMMANDS")" = "$1" ] ||
    { echo "Expected the last command to be '$1' in:" >&2; cat "$COMMANDS" >&2; exit 1; }
}

# A bare host, where provision.sh has removed the default site, still gets the
# standalone authenticator: nginx is stopped for it and started again after, and the
# renewal config certbot wrote is switched to the nginx authenticator and verified.
start_test_case
run_setup
expect_calls 'dig +short example.com' 'curl -s https://api.ipify.org' \
  'systemctl is-active --quiet nginx' \
  'systemctl is-active --quiet nginx' 'systemctl stop nginx' \
  'systemctl is-active --quiet apache2' "$STANDALONE" \
  'systemctl start nginx'
assert_line "$RENEWAL_CONF" 'authenticator = nginx'
assert_contains '\(verified\)' "$OUTPUT"

# A host whose nginx already serves a site gets the nginx authenticator through the
# running server: nothing is stopped or started, so the site stays up.
start_test_case
add_enabled_site
run_setup
expect_calls 'dig +short example.com' 'curl -s https://api.ipify.org' \
  'systemctl is-active --quiet nginx' "$NGINX_AUTHENTICATOR"
assert_contains 'already serves a site' "$OUTPUT"
assert_line "$RENEWAL_CONF" 'authenticator = nginx'
assert_contains '\(verified\)' "$OUTPUT"

# A stopped nginx with a site cannot answer the challenge, so the standalone path runs.
# Nothing was stopped, so nothing starts again, and the empty list of stopped services
# must not trip set -u under bash 3.2, which the run's exit status shows.
start_test_case
add_enabled_site
rm "$FLAGS/active-nginx"
run_setup
expect_calls 'dig +short example.com' 'curl -s https://api.ipify.org' \
  'systemctl is-active --quiet nginx' 'systemctl is-active --quiet nginx' \
  'systemctl is-active --quiet apache2' "$STANDALONE"
assert_line "$RENEWAL_CONF" 'authenticator = nginx'

# A standalone certbot that fails still starts nginx again, as the last thing it does.
start_test_case
touch "$FLAGS/certbot-fails"
expect_failure 'a failed standalone request to stop the run'
assert_last_command 'systemctl start nginx'

# An nginx certbot that fails stops and starts nothing.
start_test_case
add_enabled_site
touch "$FLAGS/certbot-fails"
expect_failure 'a failed nginx request to stop the run'
assert_last_command "$NGINX_AUTHENTICATOR"
refute_contains '^systemctl (stop|start) ' "$COMMANDS"

# A domain that resolves elsewhere stops the run before certbot or systemctl runs.
start_test_case
touch "$FLAGS/other-ip"
expect_failure 'a DNS mismatch to stop the run'
assert_contains 'resolves to' "$OUTPUT"
refute_contains '^(certbot|systemctl) ' "$COMMANDS"

# Without an email, from .env or --email, the run stops before it checks DNS.
start_test_case CERTBOT_EMAIL=
expect_failure 'a missing registration email to stop the run'
assert_contains 'no registration email' "$OUTPUT"
assert_no_commands

echo 'certbot-setup.sh regression checks passed.'
