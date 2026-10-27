#!/usr/bin/env bash
# Exercise scripts/restore-drill.sh: the real script runs in a disposable copy of the
# repository with stub docker, rclone, df, sleep, and date commands, and docker's stub
# plays the scratch Postgres from fixture files. It runs under macOS's bash 3.2 and on
# Linux in CI, so it avoids bash 4 features.
set -euo pipefail
# The umask systemd gives a service, so the directories the cases and the script make
# start out open, and the mode checks show what the script closes.
umask 022
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

# The scratch container must run the image of the db service in docker-compose.yml,
# because pg_restore refuses a dump from a newer server. This comes first: every case
# below restores into whatever image the script names.
COMPOSE_IMAGE=$(sed -n '/^  db:$/,/^  [a-z]/s/^    image: *//p' \
  "$REPO_DIR/docker-compose.yml")
SCRIPT_IMAGE=$(sed -n 's/^DRILL_IMAGE=//p' "$REPO_DIR/scripts/restore-drill.sh")
if [ -z "$COMPOSE_IMAGE" ] || [ "$COMPOSE_IMAGE" != "$SCRIPT_IMAGE" ]; then
  echo "DRILL_IMAGE is '$SCRIPT_IMAGE' in scripts/restore-drill.sh, but the db service" \
    "in docker-compose.yml uses '$COMPOSE_IMAGE'." >&2
  exit 1
fi

TEST_DIR=$(mktemp -d)
trap 'rm -rf "$TEST_DIR"' EXIT
mkdir -p "$TEST_DIR/bin" "$TEST_DIR/repo/scripts" "$TEST_DIR/uploads-source/photos"
# Redirect the host's backup and log directories into the disposable test directory.
sed -e "s|/var/backups|$TEST_DIR/backups|g" -e "s|/var/log|$TEST_DIR/log|g" \
  "$REPO_DIR/scripts/restore-drill.sh" > "$TEST_DIR/repo/scripts/restore-drill.sh"
# A second copy that names two upload columns, for the cases that check stored paths.
sed "s|^UPLOAD_COLUMNS=''\$|UPLOAD_COLUMNS='photos.file_path receipts.photo'|" \
  "$TEST_DIR/repo/scripts/restore-drill.sh" \
  > "$TEST_DIR/repo/scripts/restore-drill-with-uploads.sh"
REAL_DATE=$(command -v date)
export TEST_DIR REAL_DATE
export PATH="$TEST_DIR/bin:$PATH"
FLAGS="$TEST_DIR/flags"
DATABASE="$TEST_DIR/database"
ENV_FILE="$TEST_DIR/repo/.env"
COMMANDS="$TEST_DIR/commands"
LOG="$TEST_DIR/log/flask-react-template/restore-drill.log"
WORK_ROOT="$TEST_DIR/backups/flask-react-template"
DAILY="$WORK_ROOT/daily"
BUCKET_DIR="$TEST_DIR/bucket/test-bucket/prod"
REMOTE='spaces:test-bucket/prod'
NEWEST=20261025T023000Z
NEWEST_EPOCH=1792895400
OLDER=20261024T023000Z
CONTAINER=flask-react-template-restore-drill
RUN="docker run -d --name $CONTAINER --network none"
RUN+=' -e POSTGRES_HOST_AUTH_METHOD=trust -e POSTGRES_USER=app -e POSTGRES_DB=app'
RUN+=' postgres:16'
RESTORE="docker exec -i $CONTAINER pg_restore -U app -d app"
RESTORE+=' --no-owner --no-privileges --exit-on-error'
UNPAIRED_DUMP="db-$NEWEST\.dump has no matching uploads-$NEWEST\.tar\.gz in "

# Each stub logs its call to $TEST_DIR/commands and reads its conditions from markers
# in $TEST_DIR/flags. docker plays the scratch Postgres. It cannot start the container
# while run-fails exists, and it answers pg_isready with failures while never-ready
# exists, or while not-ready-count holds a positive number, which each failure counts
# down. Its pg_restore accepts only a dump that starts with PGDMP, as a custom-format
# one does, and keeps it in $TEST_DIR/restored.dump. Its psql answers the script's
# queries from fixture files in $TEST_DIR/database: tables/<table> holds a table's row
# count, and columns/<table>.<column> holds the first value stored in a column. rclone
# treats $TEST_DIR/bucket as the spaces: remote, which it lists while remote-configured
# exists and cannot reach while remote-unreachable exists. df reports ample free space,
# or 1000 KB while low-disk exists, and sleep returns at once.
cat > "$TEST_DIR/bin/mock-system" <<'MOCK'
#!/usr/bin/env bash
set -eu
name=${0##*/}
flags="$TEST_DIR/flags"
database="$TEST_DIR/database"
printf '%s\n' "$name $*" >> "$TEST_DIR/commands"
bucket_path() { printf '%s\n' "$TEST_DIR/bucket/${1#spaces:}"; }
# extract QUERY SED_EXPRESSION -> what the expression captures from the query. The stub
# learns a table or column name only from the SQL the script sent.
extract() { printf '%s\n' "$1" | sed "$2"; }
case "$name" in
  df)
    available=100000000
    [ ! -f "$flags/low-disk" ] || available=1000
    echo 'Filesystem 1024-blocks Used Available Capacity Mounted on'
    echo "mock 100000000 0 $available 0% /"
    ;;
  sleep) ;;
  docker)
    case "$1" in
      rm|logs) ;;
      run) [ ! -f "$flags/run-fails" ] ;;
      exec)
        for sql; do :; done  # the last argument: psql's query
        case "$*" in
          *' pg_isready '*)
            [ ! -f "$flags/never-ready" ] || exit 1
            left=$(cat "$flags/not-ready-count" 2>/dev/null || echo 0)
            if [ "$left" -gt 0 ]; then
              echo $((left - 1)) > "$flags/not-ready-count"
              exit 1
            fi
            ;;
          *' pg_restore '*)  # stdin is the dump; a custom-format one starts PGDMP
            cat > "$TEST_DIR/restored.dump"
            [ "$(head -c 5 "$TEST_DIR/restored.dump")" = PGDMP ]
            ;;
          *' psql '*)
            case "$sql" in
              *' FROM pg_tables '*) ls "$database/tables" ;;
              'SELECT count(*) FROM public.'*) cat "$database/tables/${sql##*.}" ;;
              *' information_schema.columns '*)
                table=$(extract "$sql" "s/.* table_name = '\([^']*\)'.*/\1/")
                column=$(extract "$sql" "s/.* column_name = '\([^']*\)'.*/\1/")
                [ -f "$database/columns/$table.$column" ] && echo 1 || echo 0
                ;;
              'SELECT "'*)
                column=$(extract "$sql" 's/^SELECT "\([^"]*\)" FROM.*/\1/')
                table=$(extract "$sql" 's/.* FROM public\."\([^"]*\)" WHERE.*/\1/')
                cat "$database/columns/$table.$column"
                ;;
              *) echo "Unexpected query: $sql" >&2; exit 1 ;;
            esac
            ;;
          *) echo "Unexpected docker exec: $*" >&2; exit 1 ;;
        esac
        ;;
      *) echo "Unexpected docker call: $*" >&2; exit 1 ;;
    esac
    ;;
  rclone)
    case "$1" in
      listremotes) [ ! -f "$flags/remote-configured" ] || echo 'spaces:' ;;
      # lsf --files-only <directory> lists file names; a missing directory has none.
      lsf)
        [ ! -f "$flags/remote-unreachable" ] || exit 1
        directory=$(bucket_path "$3")
        [ ! -d "$directory" ] || ls -1 "$directory"
        ;;
      copyto)
        [ ! -f "$flags/remote-unreachable" ] || exit 1
        cp "$(bucket_path "$2")" "$3"
        ;;
      *) echo "Unexpected rclone call: $*" >&2; exit 1 ;;
    esac
    ;;
esac
MOCK
# date answers the clock in $TEST_DIR/flags/now, seconds since the epoch, for the one
# call that asks for it, `date -u +%s`. Every other call goes to the real date, unlogged.
cat > "$TEST_DIR/bin/date" <<'MOCK'
#!/usr/bin/env bash
set -eu
case "$*" in
  '-u +%s') cat "$TEST_DIR/flags/now" ;;
  *) exec "$REAL_DATE" "$@" ;;
esac
MOCK
chmod +x "$TEST_DIR/bin/mock-system" "$TEST_DIR/bin/date"
for command in docker rclone df sleep; do
  ln -s mock-system "$TEST_DIR/bin/$command"
done
# A stub that did not come first on PATH would let restore-drill.sh reach a real
# container or a real bucket.
for command in docker rclone df sleep date; do
  [ "$(command -v "$command")" = "$TEST_DIR/bin/$command" ] ||
    { echo "The $command stub does not shadow the real command." >&2; exit 1; }
done

# Stand-in for scripts/alert.sh: logs the subject and body it was given, so a direct call
# from restore-drill.sh shows up.
cat > "$TEST_DIR/repo/scripts/alert.sh" <<'ALERT'
#!/usr/bin/env bash
printf 'alert.sh %s\n' "$*" >> "$TEST_DIR/commands"
ALERT

# The uploads every archive holds: two files, one in a subdirectory.
echo 'first photo' > "$TEST_DIR/uploads-source/photos/a.jpg"
echo 'second picture' > "$TEST_DIR/uploads-source/b.png"

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

# assert_mode MODE PATH -> PATH has exactly this permission mode.
assert_mode() {
  [ -n "$(find "$2" -maxdepth 0 -perm "$1")" ] ||
    { echo "Expected mode $1 on ${2##*/}" >&2; exit 1; }
}

# assert_call_count COUNT PATTERN -> exactly COUNT logged commands match PATTERN.
assert_call_count() {
  local found
  found=$(grep -Ec -- "$2" "$COMMANDS") || true
  [ "$found" -eq "$1" ] ||
    { echo "Expected $1 calls matching /$2/, found $found" >&2; exit 1; }
}

# expect_docker_calls LINE... -> docker ran exactly these lines, in this order. The psql
# queries are left out: their effects are what the cases check.
expect_docker_calls() {
  grep '^docker ' "$COMMANDS" | grep -v ' psql ' > "$TEST_DIR/docker-calls" || true
  printf '%s\n' "$@" | diff -u - "$TEST_DIR/docker-calls"
}

# set_table_counts NAME=COUNT... -> the stub's database has each table, with that many
# rows.
set_table_counts() {
  local pair
  for pair in "$@"; do
    printf '%s\n' "${pair#*=}" > "$DATABASE/tables/${pair%%=*}"
  done
}

# set_upload_column TABLE.COLUMN VALUE -> the stub's database has the column, whose
# first stored value is VALUE; an empty VALUE means the column holds nothing.
set_upload_column() {
  printf '%s\n' "$2" > "$DATABASE/columns/$1"
}

# Start a case from empty backup, bucket, log, flag, and database directories, so the
# remote is unconfigured and the host healthy; a fresh command log; a clock one hour
# after the newest fixture dump; a database whose tables pass the script's checks; and a
# .env holding what restore-drill.sh requires plus any given lines, which win because
# restore-drill.sh reads the last one.
start_test_case() {
  rm -rf "$TEST_DIR/backups" "$TEST_DIR/bucket" "$TEST_DIR/log" "$FLAGS" "$DATABASE" \
    "$TEST_DIR/restored.dump"
  mkdir -p "$TEST_DIR/backups" "$TEST_DIR/bucket" "$FLAGS" "$DATABASE/tables" \
    "$DATABASE/columns"
  : > "$COMMANDS"
  echo $((NEWEST_EPOCH + 3600)) > "$FLAGS/now"
  set_table_counts alembic_version=1 users=2 widgets=3
  printf '%s\n' APP_NAME=flask-react-template POSTGRES_USER=app POSTGRES_DB=app "$@" \
    > "$ENV_FILE"
}

# seed_backup_pair DB_DIRECTORY UPLOADS_DIRECTORY STAMP [DUMP_TEXT] -> db-STAMP.dump
# holding DUMP_TEXT, which the docker stub restores only if it starts with PGDMP, and
# uploads-STAMP.tar.gz holding the uploads source. COPYFILE_DISABLE keeps macOS's tar
# from adding ._ files, which would change the archive's file count.
seed_backup_pair() {
  mkdir -p "$1" "$2"
  printf '%s\n' "${4:-PGDMP dump of $3}" > "$1/db-$3.dump"
  COPYFILE_DISABLE=1 tar czf "$2/uploads-$3.tar.gz" -C "$TEST_DIR/uploads-source" .
}

# Run a copy of the script, which writes its output to $LOG; show the log on failure.
run_drill() {
  local script=${1:-restore-drill.sh}
  bash "$TEST_DIR/repo/scripts/$script" ||
    { echo "$script failed. Its log:" >&2; cat "$LOG" >&2; exit 1; }
}

# expect_drill_failure DESCRIPTION [SCRIPT] -> the run fails. The script writes to $LOG
# once it knows APP_NAME; anything it prints before that lands in $TEST_DIR/stderr.
expect_drill_failure() {
  if bash "$TEST_DIR/repo/scripts/${2:-restore-drill.sh}" 2> "$TEST_DIR/stderr"; then
    echo "Expected $1." >&2
    exit 1
  fi
}

# assert_drill_failed REASON -> the run logged `FAILURE: REASON`, never logged SUCCESS,
# and made no alert.sh call, since OnFailure= in restore-drill.service alerts instead.
# If it called docker at all, the last call removed the scratch container.
assert_drill_failed() {
  local last_docker_call
  assert_contains "FAILURE: $1" "$LOG"
  refute_contains 'SUCCESS' "$LOG"
  refute_contains '^alert\.sh ' "$COMMANDS"
  last_docker_call=$(grep '^docker ' "$COMMANDS" | tail -n 1 || true)
  [ -z "$last_docker_call" ] || [ "$last_docker_call" = "docker rm -f -v $CONTAINER" ] ||
    { echo "The last docker call was '$last_docker_call'." >&2; exit 1; }
}

# The second copy took its UPLOAD_COLUMNS line, and no real host path survives in the
# first. $TEST_DIR is removed before that check, since on macOS it begins /var/folders/.
assert_contains "^UPLOAD_COLUMNS='photos.file_path receipts.photo'\$" \
  "$TEST_DIR/repo/scripts/restore-drill-with-uploads.sh"
sed "s|$TEST_DIR||g" "$TEST_DIR/repo/scripts/restore-drill.sh" > "$TEST_DIR/stripped"
refute_contains '/var/' "$TEST_DIR/stripped"

# With no bucket, the drill restores the newest pair in daily/ on this host, ignoring an
# older pair and a stray file. Docker sees the leftover-container removal, the scratch
# container with no network, the readiness probe, the restore with no ownership or
# grants, and the removal on exit. The restore receives the newest dump, the log counts
# every table's rows and the archive's files, and no rclone or alert.sh call is made.
# Nothing the run made is left in the work directory, and daily/ is untouched.
start_test_case
seed_backup_pair "$DAILY" "$DAILY" "$OLDER"
seed_backup_pair "$DAILY" "$DAILY" "$NEWEST"
echo 'not a backup' > "$DAILY/notes.txt"
run_drill
expect_docker_calls "docker rm -f -v $CONTAINER" "$RUN" \
  "docker exec $CONTAINER pg_isready -q -h 127.0.0.1 -U app -d app" "$RESTORE" \
  "docker rm -f -v $CONTAINER"
assert_contains "^PGDMP dump of $NEWEST\$" "$TEST_DIR/restored.dump"
assert_contains 'rows users=2' "$LOG"
assert_contains 'rows widgets=3' "$LOG"
assert_contains 'rows alembic_version=1' "$LOG"
assert_contains "db-$NEWEST\.dump is 60 minutes old" "$LOG"
assert_contains 'holds 2 files' "$LOG"
assert_contains 'UPLOAD_COLUMNS is empty' "$LOG"
SUCCESS_LINE="SUCCESS: db-$NEWEST\.dump restored \(users=2\);"
SUCCESS_LINE+=" uploads-$NEWEST\.tar\.gz holds 2"
assert_contains "$SUCCESS_LINE" "$LOG"
refute_contains '^(rclone|alert\.sh) ' "$COMMANDS"
leftover=$(find "$WORK_ROOT" -maxdepth 1 -name 'drill.*')
[ -z "$leftover" ] || { echo "The run left $leftover behind." >&2; exit 1; }
assert_file_count 2 "$DAILY" 'db-*.dump'
assert_file_count 2 "$DAILY" 'uploads-*.tar.gz'
# The backup root is closed to everyone but root, though the case made it with the open
# default: the dump and the archive stay private because the directory is.
assert_mode 700 "$WORK_ROOT"

# Once the spaces: remote is configured, the drill takes the bucket's newest pair, even
# when this host holds a newer one, and downloads it into the run's directory.
start_test_case SPACES_BUCKET=test-bucket
touch "$FLAGS/remote-configured"
seed_backup_pair "$BUCKET_DIR/daily/db" "$BUCKET_DIR/daily/uploads" "$OLDER" \
  'PGDMP bucket dump'
seed_backup_pair "$BUCKET_DIR/daily/db" "$BUCKET_DIR/daily/uploads" "$NEWEST" \
  'PGDMP bucket dump'
seed_backup_pair "$DAILY" "$DAILY" 20261025T120000Z 'PGDMP local dump'
run_drill
assert_contains "^rclone copyto $REMOTE/daily/db/db-$NEWEST\.dump .*/drill\." \
  "$COMMANDS"
assert_contains \
  "^rclone copyto $REMOTE/daily/uploads/uploads-$NEWEST\.tar\.gz .*/drill\." "$COMMANDS"
assert_contains '^PGDMP bucket dump$' "$TEST_DIR/restored.dump"
assert_contains "from $REMOTE/daily" "$LOG"

# A configured remote that cannot be reached fails the drill before it touches docker.
start_test_case SPACES_BUCKET=test-bucket
touch "$FLAGS/remote-configured" "$FLAGS/remote-unreachable"
expect_drill_failure 'an unreachable bucket to fail the drill'
assert_drill_failed "cannot list $REMOTE/daily/db"
refute_contains '^docker ' "$COMMANDS"

# A corrupted dump fails the restore, and the container is removed.
start_test_case
seed_backup_pair "$DAILY" "$DAILY" "$NEWEST" garbage
expect_drill_failure 'a corrupted dump to fail the drill'
assert_drill_failed "pg_restore of db-$NEWEST\.dump failed"

# A restore that leaves no users, or anything but one alembic_version row, fails the
# drill, and so does a restore without either table. The container is removed each time.
start_test_case
seed_backup_pair "$DAILY" "$DAILY" "$NEWEST"
set_table_counts users=0
expect_drill_failure 'an empty users table to fail the drill'
assert_drill_failed 'users is empty after the restore'
start_test_case
seed_backup_pair "$DAILY" "$DAILY" "$NEWEST"
rm "$DATABASE/tables/users"
expect_drill_failure 'a missing users table to fail the drill'
assert_drill_failed 'the restored database has no users table'
start_test_case
seed_backup_pair "$DAILY" "$DAILY" "$NEWEST"
set_table_counts alembic_version=2
expect_drill_failure 'two alembic_version rows to fail the drill'
assert_drill_failed 'alembic_version has 2 rows, expected exactly 1'
start_test_case
seed_backup_pair "$DAILY" "$DAILY" "$NEWEST"
rm "$DATABASE/tables/alembic_version"
expect_drill_failure 'a missing alembic_version table to fail the drill'
assert_drill_failed 'the restored database has no alembic_version table'

# With nothing to restore, the drill fails without starting a container: when the host
# has no daily directory, which the script still makes private, and when it has dumps
# and no archives at all.
start_test_case
expect_drill_failure 'a host without daily backups to fail the drill'
assert_drill_failed 'no daily backups yet'
refute_contains '^docker ' "$COMMANDS"
assert_mode 700 "$WORK_ROOT"
start_test_case
seed_backup_pair "$DAILY" "$DAILY" "$OLDER"
seed_backup_pair "$DAILY" "$DAILY" "$NEWEST"
rm "$DAILY"/uploads-*.tar.gz
expect_drill_failure 'dumps without archives to fail the drill'
assert_drill_failed "$UNPAIRED_DUMP"
refute_contains '^docker ' "$COMMANDS"

# The newest dump needs the archive of its own run, not the newest archive. A run whose
# archive upload failed leaves a fresh dump beside an older run's archive, and the drill
# must not certify that. This holds on the host and in the bucket, and the drill stops
# before it downloads anything or starts a container.
start_test_case
seed_backup_pair "$DAILY" "$DAILY" "$OLDER"
seed_backup_pair "$DAILY" "$DAILY" "$NEWEST"
rm "$DAILY/uploads-$NEWEST.tar.gz"
expect_drill_failure 'a dump beside only an older archive to fail the drill'
assert_drill_failed "$UNPAIRED_DUMP$DAILY"
assert_contains 'the newest backup is incomplete' "$LOG"
refute_contains '^docker ' "$COMMANDS"
start_test_case SPACES_BUCKET=test-bucket
touch "$FLAGS/remote-configured"
seed_backup_pair "$BUCKET_DIR/daily/db" "$BUCKET_DIR/daily/uploads" "$OLDER"
seed_backup_pair "$BUCKET_DIR/daily/db" "$BUCKET_DIR/daily/uploads" "$NEWEST"
rm "$BUCKET_DIR/daily/uploads/uploads-$NEWEST.tar.gz"
expect_drill_failure 'a bucket dump beside only an older archive to fail the drill'
assert_drill_failed "$UNPAIRED_DUMP$REMOTE/daily"
refute_contains '^(docker|rclone copyto) ' "$COMMANDS"

# A newest dump up to 48 hours old passes; an older one fails, saying how old it is,
# before any container starts. A pair stamped on a leap day, with the clock an hour
# later, is an hour old: an error in the date arithmetic would show as another age.
start_test_case
seed_backup_pair "$DAILY" "$DAILY" "$NEWEST"
echo $((NEWEST_EPOCH + 47 * 3600)) > "$FLAGS/now"
run_drill
start_test_case
seed_backup_pair "$DAILY" "$DAILY" "$NEWEST"
echo $((NEWEST_EPOCH + 49 * 3600)) > "$FLAGS/now"
expect_drill_failure 'a dump more than 48 hours old to fail the drill'
assert_drill_failed "db-$NEWEST\.dump is more than 48 hours old"
assert_contains 'is 2940 minutes old' "$LOG"
refute_contains '^docker ' "$COMMANDS"
start_test_case
seed_backup_pair "$DAILY" "$DAILY" 20240229T120000Z
echo 1709211600 > "$FLAGS/now"
run_drill
assert_contains 'db-20240229T120000Z\.dump is 60 minutes old' "$LOG"

# The drill probes a slow database again after two seconds and passes once it answers,
# but gives up after 60 probes, shows the container's last log lines, and removes it.
start_test_case
seed_backup_pair "$DAILY" "$DAILY" "$NEWEST"
echo 2 > "$FLAGS/not-ready-count"
run_drill
assert_call_count 2 '^sleep 2$'
start_test_case
seed_backup_pair "$DAILY" "$DAILY" "$NEWEST"
touch "$FLAGS/never-ready"
expect_drill_failure 'a database that never accepts connections to fail the drill'
assert_drill_failed 'the scratch database did not accept connections within 2 minutes'
assert_call_count 60 ' pg_isready '
assert_call_count 59 '^sleep 2$'
assert_contains "^docker logs --tail 20 $CONTAINER\$" "$COMMANDS"

# An uploads archive that cannot be read to its end fails the drill.
start_test_case
seed_backup_pair "$DAILY" "$DAILY" "$NEWEST"
echo garbage > "$DAILY/uploads-$NEWEST.tar.gz"
expect_drill_failure 'an unreadable uploads archive to fail the drill'
assert_drill_failed "uploads archive uploads-$NEWEST\.tar\.gz is unreadable"

# For each column UPLOAD_COLUMNS names, a stored path the archive holds passes, one it
# lacks fails, and an empty column passes; a column the dump's schema lacks is skipped.
start_test_case
seed_backup_pair "$DAILY" "$DAILY" "$NEWEST"
set_upload_column photos.file_path photos/a.jpg
run_drill restore-drill-with-uploads.sh
assert_contains 'photos\.file_path: photos/a\.jpg is in the archive' "$LOG"
assert_contains "receipts\.photo: not in this dump's schema; skipped" "$LOG"
assert_contains 'SUCCESS' "$LOG"
start_test_case
seed_backup_pair "$DAILY" "$DAILY" "$NEWEST"
set_upload_column photos.file_path photos/missing.jpg
expect_drill_failure 'a stored path missing from the archive to fail the drill' \
  restore-drill-with-uploads.sh
assert_drill_failed 'photos\.file_path names photos/missing\.jpg, which'
start_test_case
seed_backup_pair "$DAILY" "$DAILY" "$NEWEST"
set_upload_column photos.file_path ''
run_drill restore-drill-with-uploads.sh
assert_contains 'photos\.file_path: no stored path; skipped' "$LOG"
assert_contains 'SUCCESS' "$LOG"

# The run checks its settings and free space before it starts a container. An empty
# APP_NAME goes to stderr, since APP_NAME locates the log, with no command run; an empty
# POSTGRES_DB or less than ~2 GB free fails the drill with no docker call. A container
# that will not start fails it too, and the removal on exit still runs.
start_test_case
seed_backup_pair "$DAILY" "$DAILY" "$NEWEST"
touch "$FLAGS/low-disk"
expect_drill_failure 'low free space to fail the drill'
assert_drill_failed 'less than ~2GB free'
refute_contains '^docker ' "$COMMANDS"
start_test_case
seed_backup_pair "$DAILY" "$DAILY" "$NEWEST"
touch "$FLAGS/run-fails"
expect_drill_failure 'a container that will not start to fail the drill'
assert_drill_failed 'cannot start a scratch container from postgres:16'
expect_docker_calls "docker rm -f -v $CONTAINER" "$RUN" "docker rm -f -v $CONTAINER"
start_test_case POSTGRES_DB=
seed_backup_pair "$DAILY" "$DAILY" "$NEWEST"
expect_drill_failure 'an empty POSTGRES_DB to fail the drill'
assert_drill_failed 'POSTGRES_USER and POSTGRES_DB must be set'
refute_contains '^docker ' "$COMMANDS"
start_test_case APP_NAME=
expect_drill_failure 'an empty APP_NAME to fail the drill'
assert_contains 'ERROR: APP_NAME is empty' "$TEST_DIR/stderr"
refute_contains '.' "$COMMANDS"

echo 'Restore drill regression checks passed.'
