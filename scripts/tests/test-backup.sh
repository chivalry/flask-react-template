#!/usr/bin/env bash
# Exercise scripts/backup.sh's daily and pre-migration modes, its local daily copies, its
# labels and Compose override, and its retention settings: the real script runs in a
# disposable copy of the repository, with stub docker, rclone, df, hostname, and date
# commands and a stub scripts/alert.sh. It is Linux-only: backup.sh needs bash 4
# (mapfile) and GNU tail -z, and the rclone stub uses GNU find -printf and stat -c, none
# of which macOS has. Elsewhere it exits 77, which scripts/tests/run-all.sh counts as a
# skip outside CI. CI runs it directly; on a Mac, run it in a container from the
# repository root:
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
mkdir -p "$TEST_DIR/repo/docker"
# backup.sh refuses a Compose override that does not exist; empty files will do.
for compose_file in docker-compose.yml docker/docker-compose.prod.yml \
  docker/docker-compose.alt.yml; do
  : > "$TEST_DIR/repo/$compose_file"
done
REAL_DATE=$(command -v date)
export TEST_DIR REAL_DATE
export PATH="$TEST_DIR/bin:$PATH"
FLAGS="$TEST_DIR/flags"
ENV_FILE="$TEST_DIR/repo/.env"
COMMANDS="$TEST_DIR/commands"
LOG="$TEST_DIR/log/flask-react-template/backup.log"
PRE_MIGRATION="$TEST_DIR/backups/flask-react-template/pre-migration"
DAILY="$TEST_DIR/backups/flask-react-template/daily"
BUCKET_DIR="$TEST_DIR/bucket/test-bucket/prod"
REMOTE='spaces:test-bucket/prod'
STAMP='[0-9]{8}T[0-9]{6}Z'
DUMP='^docker compose -f docker-compose\.yml -f docker/docker-compose\.prod\.yml'
DUMP+=' --env-file \.env exec -T db pg_dump -U app -d app -Fc$'
ALT_DUMP=' -f docker/docker-compose\.alt\.yml --env-file \.env exec -T db pg_dump '
ARCHIVE='^docker run --rm -v flask-react-template_uploads_data:/from:ro -v .*:/backup'
ARCHIVE+=" alpine tar czf /backup/uploads-$STAMP\.tar\.gz -C /from \.$"

# Each stub logs its call to $TEST_DIR/commands and reads its conditions from markers
# in $TEST_DIR/flags. docker stands in for the dump, the volume check, and the archive,
# and finds no uploads volume while no-uploads-volume exists. rclone treats
# $TEST_DIR/bucket as the spaces: remote, which it lists while remote-configured exists
# and cannot reach while remote-unreachable exists; its uploads also fail while
# upload-fails exists. Its listremotes names spaces: first and then more remotes than a
# pipe holds, so a reader that quits at the match kills it with SIGPIPE, and its copyto
# records how many names each uploaded file has in $TEST_DIR/link-counts. df reports
# ample free space, or 1000 KB while low-disk exists.
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
      listremotes)
        if [ -f "$flags/remote-configured" ]; then
          echo 'spaces:'
          yes other-remote: | head -n 50000
        fi
        ;;
      lsd)
        [ -f "$flags/remote-configured" ] || exit 1
        [ ! -f "$flags/remote-unreachable" ] || exit 1
        ;;
      copyto)
        [ ! -f "$flags/remote-unreachable" ] || exit 1
        [ ! -f "$flags/upload-fails" ] || exit 1
        # The source's link count: backup.sh links each file into daily/ before it pushes.
        printf '%s %s\n' "$(stat -c %h "$2")" "${2##*/}" >> "$TEST_DIR/link-counts"
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
  rm -rf "$TEST_DIR/backups" "$TEST_DIR/bucket" "$TEST_DIR/log" "$FLAGS" \
    "$TEST_DIR/link-counts"
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

# expect_usage_error MESSAGE [ARGUMENT...] -> the run exits with status 2 and MESSAGE on
# stderr, before it runs any command or writes the log.
expect_usage_error() {
  local message=$1 status=0
  shift
  bash "$TEST_DIR/repo/scripts/backup.sh" "$@" 2> "$TEST_DIR/stderr" || status=$?
  [ "$status" -eq 2 ] ||
    { echo "Expected exit status 2 from backup.sh $*, got $status" >&2; exit 1; }
  assert_contains "$message" "$TEST_DIR/stderr"
  refute_contains . "$COMMANDS"
  [ ! -e "$LOG" ] || { echo "Unexpected log after a usage error: $LOG" >&2; exit 1; }
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

# .env.example sets every variable backup.sh reads, which catches one added to the script
# and not to the example. The first check keeps the loop from passing on an empty list.
grep -o '\$(get [A-Z][A-Z0-9_]*)' "$REPO_DIR/scripts/backup.sh" |
  sed 's/^\$(get \(.*\))$/\1/' | sort -u > "$TEST_DIR/read-keys"
assert_contains '^BACKUP_COMPOSE_FILE$' "$TEST_DIR/read-keys"
while IFS= read -r key; do
  grep -Eq "^$key=" "$REPO_DIR/.env.example" ||
    { echo "backup.sh reads $key, which .env.example lacks." >&2; exit 1; }
done < "$TEST_DIR/read-keys"

# Without the rclone remote, a daily run keeps its local copies and stops with a
# warning: the newest RETAIN_LOCAL_DAILY (default 7) of each kind stay in daily/, this
# run's included. With no bucket set, it does not even look for the remote.
start_test_case
seed_older_backups "$DAILY" db .dump 8
seed_older_backups "$DAILY" uploads .tar.gz 8
run_backup
assert_contains "$DUMP" "$COMMANDS"
assert_contains "$ARCHIVE" "$COMMANDS"
assert_contains 'WARN: Spaces remote not configured; kept LOCAL daily backup only' "$LOG"
refute_contains '^rclone ' "$COMMANDS"
refute_contains '^alert\.sh ' "$COMMANDS"
assert_file_count 7 "$DAILY" 'db-*.dump'
assert_file_count 7 "$DAILY" 'uploads-*.tar.gz'
assert_file_count 6 "$DAILY" 'db-2020*'
assert_file_count 6 "$DAILY" 'uploads-2020*'
assert_file_count 0 "$DAILY" '*-2020010[12]T*'

# RETAIN_LOCAL_DAILY sets how many copies of each kind stay.
start_test_case RETAIN_LOCAL_DAILY=2
seed_older_backups "$DAILY" db .dump 3
seed_older_backups "$DAILY" uploads .tar.gz 3
run_backup
assert_file_count 2 "$DAILY" 'db-*.dump'
assert_file_count 2 "$DAILY" 'uploads-*.tar.gz'
assert_file_count 1 "$DAILY" 'db-2020*'
assert_file_count 1 "$DAILY" 'uploads-2020*'

# A bucket without the rclone remote, as on a server before install-backup.sh runs, is
# still local-only: the run looks for the remote, finds none, and pushes nothing.
start_test_case SPACES_BUCKET=test-bucket
run_backup
assert_contains 'WARN: Spaces remote not configured; kept LOCAL daily backup only' "$LOG"
assert_contains '^rclone listremotes' "$COMMANDS"
refute_contains '^rclone copyto' "$COMMANDS"
assert_file_count 1 "$DAILY" 'db-*.dump'
assert_file_count 1 "$DAILY" 'uploads-*.tar.gz'

# A configured remote that cannot be reached fails the run, but only after both local
# copies are written, and nothing is pushed.
start_test_case SPACES_BUCKET=test-bucket
touch "$FLAGS/remote-configured" "$FLAGS/remote-unreachable"
expect_failure 'a daily run with an unreachable remote to fail'
assert_contains '^rclone lsd spaces:test-bucket$' "$COMMANDS"
assert_failure_reported daily 'Spaces not configured/reachable'
assert_file_count 1 "$DAILY" 'db-*.dump'
assert_file_count 1 "$DAILY" 'uploads-*.tar.gz'
refute_contains '^rclone copyto' "$COMMANDS"

# With the remote, a daily run archives the uploads volume COMPOSE_PROJECT_NAME names and
# pushes both files to daily/, which keeps the newest RETAIN_DAILY of each kind, this
# run's included, and keeps a local copy of each. An ordinary weekday pushes no weekly
# or monthly copy.
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
assert_file_count 1 "$DAILY" 'db-*.dump'
assert_file_count 1 "$DAILY" 'uploads-*.tar.gz'
# backup.sh links each file into daily/ before it pushes, so a pushed file has two names,
# the run's and daily/'s; a copy would leave it one.
assert_contains '^2 db-' "$TEST_DIR/link-counts"
assert_contains '^2 uploads-' "$TEST_DIR/link-counts"
refute_contains '^1 ' "$TEST_DIR/link-counts"
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

# A missing uploads volume fails the run instead of archiving an empty one, and no local
# copy is written. With no bucket, the run reaches the archive step on its own.
start_test_case
touch "$FLAGS/no-uploads-volume"
expect_failure 'a missing uploads volume to fail the run'
assert_failure_reported daily \
  'uploads volume flask-react-template_uploads_data not found'
refute_contains '^docker run |^rclone copyto' "$COMMANDS"
assert_file_count 0 "$DAILY" '*'

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

# --label names the dump db-<stamp>-<label>.dump. A pre-migration dump without the
# remote stays on the host with its label, and the run writes no daily copy.
start_test_case
run_backup --pre-migration --label abc1234
assert_file_count 1 "$PRE_MIGRATION" 'db-*-abc1234.dump'
assert_contains 'WARN: Spaces remote not configured yet; kept LOCAL pre-migration' "$LOG"
[ ! -e "$DAILY" ] || { echo "A pre-migration run wrote $DAILY" >&2; exit 1; }

# With the remote configured, the labelled dump goes to premigration/ in the bucket too.
start_test_case SPACES_BUCKET=test-bucket
touch "$FLAGS/remote-configured"
run_backup --pre-migration --label abc1234
assert_contains "^rclone copyto .* $REMOTE/premigration/db-$STAMP-abc1234\.dump$" \
  "$COMMANDS"
assert_contains \
  "pre-migration backup OK \(local \+ Spaces\): db-$STAMP-abc1234\.dump" "$LOG"
assert_file_count 1 "$BUCKET_DIR/premigration" 'db-*-abc1234.dump'

# A labelled dump counts toward the newest three like any other.
start_test_case
seed_older_backups "$PRE_MIGRATION" db .dump 4
run_backup --pre-migration --label abc1234
assert_file_count 3 "$PRE_MIGRATION" 'db-*.dump'
assert_file_count 1 "$PRE_MIGRATION" 'db-*-abc1234.dump'
assert_file_count 2 "$PRE_MIGRATION" 'db-2020*'

# A labelled daily run names its dump in daily/, in the bucket, and in the SUCCESS line.
start_test_case SPACES_BUCKET=test-bucket
touch "$FLAGS/remote-configured"
run_backup --label nightly
assert_file_count 1 "$DAILY" 'db-*-nightly.dump'
assert_file_count 1 "$BUCKET_DIR/daily/db" 'db-*-nightly.dump'
assert_contains "SUCCESS: db-$STAMP-nightly\.dump \+ uploads-$STAMP\.tar\.gz uploaded" \
  "$LOG"

# A malformed command line exits 2 with its message on stderr, before the run does or
# logs anything.
start_test_case
expect_usage_error 'may contain only letters' --label 'a/b'
expect_usage_error '--label needs a value' --label
expect_usage_error '--compose-file needs a path' --compose-file
expect_usage_error 'Unknown option: --bogus' --bogus

# BACKUP_COMPOSE_FILE picks the Compose override, and --compose-file wins over it.
start_test_case BACKUP_COMPOSE_FILE=docker/docker-compose.alt.yml
run_backup
assert_contains "$ALT_DUMP" "$COMMANDS"
refute_contains 'docker-compose\.prod\.yml' "$COMMANDS"
start_test_case BACKUP_COMPOSE_FILE=docker/docker-compose.alt.yml
run_backup --compose-file docker/docker-compose.prod.yml
assert_contains "$DUMP" "$COMMANDS"
refute_contains 'docker-compose\.alt\.yml' "$COMMANDS"

# A Compose file that does not exist fails the run with a logged FAILURE and an alert,
# not a bare exit before there is a log, and nothing runs.
start_test_case BACKUP_COMPOSE_FILE=docker/missing.yml
expect_failure 'a missing Compose file to fail the run'
assert_failure_reported daily 'no Compose file at docker/missing\.yml'
refute_contains '^docker ' "$COMMANDS"

# Every retention count must be a whole number above 0: 0 would delete this run's own
# copy, and a leading zero reads as octal.
RETAIN_FAILURE='RETAIN_\* counts must be whole numbers above 0'
start_test_case RETAIN_LOCAL_DAILY=0
expect_failure 'RETAIN_LOCAL_DAILY=0 to fail the run'
assert_failure_reported daily "$RETAIN_FAILURE \(got '0'\)"
refute_contains '^docker ' "$COMMANDS"
start_test_case RETAIN_DAILY=08
expect_failure 'RETAIN_DAILY=08 to fail the run'
assert_failure_reported daily "$RETAIN_FAILURE \(got '08'\)"
refute_contains '^docker ' "$COMMANDS"

echo 'Backup regression checks passed.'
