#!/usr/bin/env bash
# Exercise scripts/install-backup.sh: the real script runs in a disposable copy of the
# repository whose rclone, log, backup, and systemd paths point into a test directory,
# with stub rclone, systemctl, and apt-get commands. It runs under macOS's bash 3.2 and
# on Linux in CI, so it avoids bash 4 features.
set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TEST_DIR=$(mktemp -d)
trap 'rm -rf "$TEST_DIR"' EXIT
mkdir -p "$TEST_DIR/bin" "$TEST_DIR/repo/scripts"
INSTALLER="$TEST_DIR/repo/scripts/install-backup.sh"
# Redirect the host's rclone config, log, backup, and systemd directories into the
# disposable test directory.
sed -e "s|/root/\.config/rclone|$TEST_DIR/rclone|g" \
  -e "s|/var/log|$TEST_DIR/log|g" -e "s|/var/backups|$TEST_DIR/backups|g" \
  -e "s|/etc/systemd/system|$TEST_DIR/systemd|g" \
  "$REPO_DIR/scripts/install-backup.sh" > "$INSTALLER"
cp -R "$REPO_DIR/scripts/systemd" "$TEST_DIR/repo/scripts/"
export TEST_DIR
export PATH="$TEST_DIR/bin:$PATH"
APP=flask-react-template
FLAGS="$TEST_DIR/flags"
SYSTEMD="$TEST_DIR/systemd"
RCLONE_CONF="$TEST_DIR/rclone/rclone.conf"
ENV_FILE="$TEST_DIR/repo/.env"
COMMANDS="$TEST_DIR/commands"
OUTPUT="$TEST_DIR/output"
PROBE='spaces:test-bucket/.install-write-probe'
ENABLE_TIMERS="systemctl enable --now $APP-backup.timer $APP-restore-drill.timer"

# Each stub logs its call to $TEST_DIR/commands and reads its conditions from markers in
# $TEST_DIR/flags. rclone cannot list the bucket while unreadable exists, and cannot
# write the probe while unwritable exists. systemctl and apt-get only log; the rclone
# stub puts rclone on PATH, so the installer never calls apt-get.
cat > "$TEST_DIR/bin/mock-command" <<'MOCK'
#!/usr/bin/env bash
set -eu
name=${0##*/}
printf '%s %s\n' "$name" "$*" >> "$TEST_DIR/commands"
if [ "$name" = rclone ]; then
  case "$1" in
    lsd) [ ! -f "$TEST_DIR/flags/unreadable" ] || exit 1 ;;
    rcat)
      # Read the probe the way rclone does: a stub that exits first can kill the
      # installer's echo with SIGPIPE, and pipefail would report an unwritable bucket.
      cat > /dev/null
      [ ! -f "$TEST_DIR/flags/unwritable" ] || exit 1
      ;;
    deletefile) ;;
    *) echo "Unexpected rclone call: $*" >&2; exit 1 ;;
  esac
fi
MOCK
chmod +x "$TEST_DIR/bin/mock-command"
# A stub that did not come first on PATH would let the installer reach a real bucket,
# systemd, or the package manager.
for command in rclone systemctl apt-get; do
  ln -s mock-command "$TEST_DIR/bin/$command"
  [ "$(command -v "$command")" = "$TEST_DIR/bin/$command" ] ||
    { echo "The $command stub does not shadow the real command." >&2; exit 1; }
done

# write_env [LINE...] -> .env holds what install-backup.sh reads plus any given lines,
# which win because its get() takes the last matching one.
write_env() {
  printf '%s\n' "APP_NAME=$APP" SPACES_ENDPOINT=https://nyc3.digitaloceanspaces.com \
    SPACES_REGION=nyc3 SPACES_BUCKET=test-bucket SPACES_ACCESS_KEY_ID=test-key \
    SPACES_SECRET_ACCESS_KEY=test-secret "$@" > "$ENV_FILE"
}

# Start a case with no rclone config, log or backup directory, or installed units; a
# bucket that is readable and writable, since no marker says otherwise; and a .env from
# write_env.
start_test_case() {
  rm -rf "$TEST_DIR/rclone" "$TEST_DIR/log" "$TEST_DIR/backups" "$SYSTEMD" "$FLAGS"
  mkdir -p "$SYSTEMD" "$FLAGS"
  write_env "$@"
}

# Run the copy's install-backup.sh with a fresh command log and its output in $OUTPUT;
# show the output on failure.
run_install_backup() {
  : > "$COMMANDS"
  bash "$INSTALLER" > "$OUTPUT" 2>&1 ||
    { echo 'install-backup.sh failed. Its output:' >&2; cat "$OUTPUT" >&2; exit 1; }
}

# expect_failure DESCRIPTION -> the run exits 1, with its output in $OUTPUT.
expect_failure() {
  local status=0
  : > "$COMMANDS"
  bash "$INSTALLER" > "$OUTPUT" 2>&1 || status=$?
  [ "$status" -eq 1 ] ||
    { echo "Expected $1 (exit status 1), got $status. Its output:" >&2
      cat "$OUTPUT" >&2; exit 1; }
}

# expect_calls LINE... -> the stubs ran exactly these lines, in this order.
expect_calls() {
  printf '%s\n' "$@" | diff -u - "$COMMANDS"
}

# expect_no_calls -> the stubs ran nothing.
expect_no_calls() {
  [ ! -s "$COMMANDS" ] ||
    { echo 'Unexpected stub calls:' >&2; cat "$COMMANDS" >&2; exit 1; }
}

# A bare `! grep` never fails under set -e, so both checks exit explicitly.
assert_contains() {
  grep -Eq -- "$1" "$2" || { echo "Missing /$1/ in ${2##*/}" >&2; exit 1; }
}

refute_contains() {
  if grep -Eq -- "$1" "$2"; then echo "Unexpected /$1/ in ${2##*/}" >&2; exit 1; fi
}

# assert_file_count COUNT DIRECTORY PATTERN -> exactly COUNT files in DIRECTORY have
# names matching PATTERN.
assert_file_count() {
  local found
  found=$(find "$2" -maxdepth 1 -type f -name "$3" 2>/dev/null | wc -l) || true
  [ "$found" -eq "$1" ] ||
    { echo "Expected $1 files matching $3 in ${2##*/}, found $found" >&2; exit 1; }
}

# No host path may survive the rewrite, or a run would reach the real system. The
# rewritten paths begin with $TEST_DIR, which starts with /var/folders/ on macOS, so the
# check reads the copy without it.
sed "s|$TEST_DIR||g" "$INSTALLER" > "$TEST_DIR/installer-without-test-dir"
refute_contains '/(etc|root|var)/' "$TEST_DIR/installer-without-test-dir"

# With a bucket it can list and write, the installer writes the rclone remote, lists the
# bucket, writes and deletes a probe file, renders the five units, and then reloads
# systemd and enables the backup and restore-drill timers in one call. rclone is already
# installed, so apt-get never runs.
start_test_case
run_install_backup
expect_calls 'rclone lsd spaces:test-bucket' "rclone rcat $PROBE" \
  "rclone deletefile $PROBE" 'systemctl daemon-reload' "$ENABLE_TIMERS"
refute_contains '^apt-get ' "$COMMANDS"
assert_contains '^\[spaces\]$' "$RCLONE_CONF"
assert_contains '^provider = DigitalOcean$' "$RCLONE_CONF"
assert_contains '^access_key_id = test-key$' "$RCLONE_CONF"
assert_contains '^secret_access_key = test-secret$' "$RCLONE_CONF"
assert_contains '^region = nyc3$' "$RCLONE_CONF"
assert_contains '^endpoint = https://nyc3\.digitaloceanspaces\.com$' "$RCLONE_CONF"
[ -n "$(find "$TEST_DIR/rclone" -name rclone.conf -perm 600)" ] ||
  { echo 'rclone.conf is not mode 600.' >&2; exit 1; }
assert_file_count 5 "$SYSTEMD" '*'
for unit in backup.service backup.timer restore-drill.service restore-drill.timer \
  alert-restore-drill.service; do
  [ -f "$SYSTEMD/$APP-$unit" ] || { echo "Missing the unit $APP-$unit." >&2; exit 1; }
  refute_contains '__[A-Z_]+__' "$SYSTEMD/$APP-$unit"
done
wrong_mode=$(find "$SYSTEMD" -type f ! -perm 644)
[ -z "$wrong_mode" ] || { echo "Units not mode 644: $wrong_mode" >&2; exit 1; }
for directory in "$TEST_DIR/log/$APP" "$TEST_DIR/backups/$APP"; do
  [ -d "$directory" ] || { echo "Missing the directory $directory." >&2; exit 1; }
done
assert_contains "systemctl start $APP-restore-drill\.service" "$OUTPUT"

# Without a bucket the installer stops before it writes the remote or runs anything.
start_test_case SPACES_BUCKET=
expect_failure 'an empty SPACES_BUCKET to fail the run'
assert_contains 'nothing to back up to' "$OUTPUT"
expect_no_calls
assert_file_count 0 "$TEST_DIR/rclone" 'rclone.conf'

# Without an app name it stops before it runs anything, too.
start_test_case APP_NAME=
expect_failure 'an empty APP_NAME to fail the run'
assert_contains 'ERROR: APP_NAME is empty' "$OUTPUT"
expect_no_calls

# A bucket the credentials cannot list stops the run at the listing: no probe, no units,
# and no systemd call. The message says what still works, since deploys enable the timers.
start_test_case
touch "$FLAGS/unreadable"
expect_failure 'an unreadable bucket to fail the run'
expect_calls 'rclone lsd spaces:test-bucket'
assert_contains 'until then bucket pushes fail and alert' "$OUTPUT"
assert_file_count 0 "$SYSTEMD" '*'

# A bucket that lists but refuses the probe stops the run at the write, so the probe is
# never deleted.
start_test_case
touch "$FLAGS/unwritable"
expect_failure 'an unwritable bucket to fail the run'
expect_calls 'rclone lsd spaces:test-bucket' "rclone rcat $PROBE"
assert_contains 'and alert, and deploys stop at their pre-migration backup' "$OUTPUT"
assert_file_count 0 "$SYSTEMD" '*'

# A second run after a key change replaces the remote: the new key is in rclone.conf and
# the old one is gone.
start_test_case
run_install_backup
assert_contains '^access_key_id = test-key$' "$RCLONE_CONF"
write_env SPACES_ACCESS_KEY_ID=rotated-key
run_install_backup
assert_contains '^access_key_id = rotated-key$' "$RCLONE_CONF"
refute_contains 'test-key' "$RCLONE_CONF"

echo 'install-backup.sh regression checks passed.'
