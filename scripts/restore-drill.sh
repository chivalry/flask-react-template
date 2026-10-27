#!/usr/bin/env bash
# Weekly restore drill: prove the newest daily backup restores. It takes the newest
# daily/db dump and the daily/uploads archive of the same run, which carries the same
# timestamp, from the bucket once the rclone remote 'spaces:' that install-backup.sh
# writes is configured and otherwise from /var/backups/<APP_NAME>/daily, restores the
# dump into a scratch Postgres container that has no network, and fails unless:
#   - the dump is at most MAX_AGE_HOURS old, so backups that stopped are reported;
#   - the dump's archive exists, so a run whose archive upload failed is reported;
#   - users has rows and alembic_version exactly one (every table's count is logged);
#   - the archive reads to its end, and for each UPLOAD_COLUMNS column the restored
#     schema has, one stored path is in it.
# The container, its volume, and the run's files are removed however it exits. Logs to
# /var/log/<APP_NAME>/restore-drill.log. It never calls alert.sh: OnFailure= in
# restore-drill.service reports every failed or timed-out run, so a call here would
# alert twice. Run it as `systemctl start <APP_NAME>-restore-drill.service`; run with
# bash directly, it logs the same but alerts nobody. It stays bash 3.2-compatible so
# scripts/tests/test-restore-drill.sh runs on macOS too.
set -Eeuo pipefail

# pg_restore refuses a dump from a newer server, so this must be the db service's image
# in docker-compose.yml; scripts/tests/test-restore-drill.sh fails when they differ.
DRILL_IMAGE=postgres:16
# Columns that hold a path inside the uploads volume, as space-separated table.column
# pairs such as 'photos.file_path receipts.photo'. Add one with the migration that
# creates it; a column the restored schema lacks is skipped. The template has none.
UPLOAD_COLUMNS=''
# backup.timer dumps daily, so a newest dump older than this means backups stopped.
MAX_AGE_HOURS=48

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
cd "$REPO_DIR"

get() { grep -E "^$1=" .env | tail -1 | cut -d= -f2- || true; }

# APP_NAME locates the log, so it is checked before output is redirected there.
APP_NAME="$(get APP_NAME)"
if [ -z "$APP_NAME" ]; then
  echo "ERROR: APP_NAME is empty in $REPO_DIR/.env; cannot locate the log directory." >&2
  exit 1
fi
LOG_DIR="/var/log/$APP_NAME"
WORK_ROOT="/var/backups/$APP_NAME"
DAILY="$WORK_ROOT/daily"
mkdir -p "$LOG_DIR" "$WORK_ROOT"
# backup.sh keeps the dumps and archives here private. If the drill is the first to make
# the directory, or an older version left it at the default 755, it closes the directory
# the same way.
chmod 700 "$WORK_ROOT"
exec >>"$LOG_DIR/restore-drill.log" 2>&1

log() { printf '%s [restore-drill] %s\n' "$(date -u +%FT%TZ)" "$*"; }
# Every failure ends here, the ERR trap's included (set -E carries it into functions).
# Never call fail inside $(...): its line would be captured instead of logged, so
# helpers used that way return a status and their callers add || fail "<reason>".
fail() { log "FAILURE: $*"; exit 1; }
trap 'fail "error at line $LINENO"' ERR

CONTAINER="$APP_NAME-restore-drill"
CONTAINER_STARTED=0
TMP=''
# -v also removes the anonymous volume the postgres image declares for its data, which
# would otherwise keep a restored copy of the database after every drill.
remove_scratch_container_and_files() {
  if [ "$CONTAINER_STARTED" = 1 ]; then
    docker rm -f -v "$CONTAINER" >/dev/null 2>&1 || true
  fi
  if [ -n "$TMP" ]; then rm -rf "$TMP"; fi
}
trap remove_scratch_container_and_files EXIT

PG_USER="$(get POSTGRES_USER)"
PG_DB="$(get POSTGRES_DB)"
[ -n "$PG_USER" ] && [ -n "$PG_DB" ] \
  || fail "POSTGRES_USER and POSTGRES_DB must be set in .env"
BUCKET="$(get SPACES_BUCKET)"
PREFIX="$(get BACKUP_PREFIX)"; PREFIX="${PREFIX:-prod}"
REMOTE="spaces:${BUCKET}/${PREFIX}"

# Docker keeps the scratch cluster under its data root, on the same disk as
# /var/backups on a single-disk server.
AVAIL_KB="$(df -Pk "$WORK_ROOT" | awk 'NR==2 {print $4}')"
[ "$AVAIL_KB" -gt 2000000 ] || fail "less than ~2GB free on $WORK_ROOT"
TMP="$(mktemp -d "$WORK_ROOT/drill.XXXXXX")"

# --- the newest pair: from the bucket once backup.sh pushes there, else this host ---
# The test backup.sh's spaces_remote_configured makes, also reading to the end.
spaces_remote_configured() {
  [ -n "$BUCKET" ] && rclone listremotes 2>/dev/null | grep -x 'spaces:' >/dev/null
}
# Each listing goes to a file on its own line: a failure inside a pipeline or a process
# substitution would pass for an empty directory (see prune() in backup.sh).
if spaces_remote_configured; then
  SOURCE="$REMOTE/daily"
  rclone lsf --files-only "$SOURCE/db" > "$TMP/db.list" \
    || fail "cannot list $SOURCE/db"
  rclone lsf --files-only "$SOURCE/uploads" > "$TMP/uploads.list" \
    || fail "cannot list $SOURCE/uploads"
else
  SOURCE="$DAILY"
  [ -d "$DAILY" ] || fail "no daily backups yet: $DAILY does not exist"
  ls -1 "$DAILY" > "$TMP/db.list"
  cp "$TMP/db.list" "$TMP/uploads.list"
fi
# newest_matching_name <listing> <regex>: the last matching name in name order, which
# timestamped names make time order; empty when nothing matches.
newest_matching_name() { grep -E -- "$2" "$1" | LC_ALL=C sort | tail -n 1 || true; }
DB_NAME="$(newest_matching_name "$TMP/db.list" '^db-[0-9]{8}T[0-9]{6}Z.*\.dump$')"
[ -n "$DB_NAME" ] || fail "no daily database dump in $SOURCE"
# backup.sh gives a run's dump and archive the same timestamp, and pushes the dump first.
# The newest archive is the wrong one to pair with the newest dump when the archive's
# upload failed: it belongs to an older run. Take the archive that carries the dump's
# timestamp, or call the backup incomplete.
UP_NAME="uploads-${DB_NAME:3:16}.tar.gz"
grep -Fxq -- "$UP_NAME" "$TMP/uploads.list" ||
  fail "$DB_NAME has no matching $UP_NAME in $SOURCE: the newest backup is incomplete"

# --- freshness ---
# stamp_to_epoch_seconds <YYYYmmddTHHMMSSZ>: seconds since the epoch, in shell
# arithmetic so that no GNU date is needed. Days come from Howard Hinnant's
# days_from_civil (howardhinnant.github.io/date_algorithms.html), exact for years
# from 0; 10# keeps 08 and 09 from reading as octal.
stamp_to_epoch_seconds() {
  local year=$((10#${1:0:4})) month=$((10#${1:4:2})) day=$((10#${1:6:2}))
  local era year_of_era day_of_year day_of_era days
  [ "$month" -gt 2 ] || year=$((year - 1))
  era=$((year / 400))
  year_of_era=$((year - era * 400))
  day_of_year=$(( (153 * (month > 2 ? month - 3 : month + 9) + 2) / 5 + day - 1 ))
  day_of_era=$((year_of_era * 365 + year_of_era / 4 - year_of_era / 100 + day_of_year))
  days=$((era * 146097 + day_of_era - 719468))
  echo $((days * 86400 + 10#${1:9:2} * 3600 + 10#${1:11:2} * 60 + 10#${1:13:2}))
}
AGE=$(( $(date -u +%s) - $(stamp_to_epoch_seconds "${DB_NAME:3:16}") ))
log "newest daily dump $DB_NAME is $(( AGE / 60 )) minutes old"
[ "$AGE" -le $(( MAX_AGE_HOURS * 3600 )) ] \
  || fail "$DB_NAME is more than $MAX_AGE_HOURS hours old: backups have stopped" \
    "reaching $SOURCE (check $APP_NAME-backup.timer and backup.log)"

# --- fetch into the run's directory ---
if [ "$SOURCE" = "$DAILY" ]; then
  # Hard links pin the pair at no cost: a backup that prunes daily/ meanwhile cannot
  # take it away mid-drill.
  ln "$DAILY/$DB_NAME" "$DAILY/$UP_NAME" "$TMP/" \
    || fail "$DB_NAME or $UP_NAME vanished from $DAILY"
else
  rclone copyto "$SOURCE/db/$DB_NAME" "$TMP/$DB_NAME" \
    || fail "cannot download $DB_NAME"
  rclone copyto "$SOURCE/uploads/$UP_NAME" "$TMP/$UP_NAME" \
    || fail "cannot download $UP_NAME"
fi
DB_FILE="$TMP/$DB_NAME"
UP_FILE="$TMP/$UP_NAME"
log "restoring $DB_NAME and reading $UP_NAME from $SOURCE"

# --- scratch database ---
docker rm -f -v "$CONTAINER" >/dev/null 2>&1 || true  # left by a run killed outright
CONTAINER_STARTED=1
# Nothing can reach a container with no network, so trust authentication is safe, and
# production's role and database names restore the dump as a rebuilt server would.
docker run -d --name "$CONTAINER" --network none \
  -e POSTGRES_HOST_AUTH_METHOD=trust -e POSTGRES_USER="$PG_USER" \
  -e POSTGRES_DB="$PG_DB" "$DRILL_IMAGE" >/dev/null \
  || fail "cannot start a scratch container from $DRILL_IMAGE"
# The image's first start runs initdb behind a temporary server that listens only on its
# Unix socket, then restarts it; a TCP probe answers only once the final server is up.
attempt=0
until docker exec "$CONTAINER" pg_isready -q -h 127.0.0.1 -U "$PG_USER" -d "$PG_DB"; do
  attempt=$((attempt + 1))
  if [ "$attempt" -ge 60 ]; then
    docker logs --tail 20 "$CONTAINER" || true
    fail "the scratch database did not accept connections within 2 minutes"
  fi
  sleep 2
done
# The scratch cluster has only the one role, so ownership and grants that name any other
# role are skipped rather than allowed to stop an --exit-on-error restore.
docker exec -i "$CONTAINER" pg_restore -U "$PG_USER" -d "$PG_DB" \
  --no-owner --no-privileges --exit-on-error < "$DB_FILE" \
  || fail "pg_restore of $DB_NAME failed"

# query_scratch_database <sql>: one query against the restored copy, unaligned and
# tuples only; </dev/null keeps it from reading the loop's input below.
query_scratch_database() {
  docker exec "$CONTAINER" psql -U "$PG_USER" -d "$PG_DB" -tAqc "$1" < /dev/null
}

# --- row counts: every table's is logged; users and alembic_version are checked ---
TABLES="SELECT quote_ident(tablename) FROM pg_tables WHERE schemaname = 'public'"
query_scratch_database "$TABLES ORDER BY 1" > "$TMP/tables" \
  || fail "cannot list the restored tables"
: > "$TMP/counts"
while IFS= read -r table; do
  count="$(query_scratch_database "SELECT count(*) FROM public.$table")" \
    || fail "cannot count the rows of $table"
  log "rows $table=$count"
  printf '%s %s\n' "$table" "$count" >> "$TMP/counts"
done < "$TMP/tables"
USERS="$(awk '$1 == "users" { print $2 }' "$TMP/counts")"
ALEMBIC="$(awk '$1 == "alembic_version" { print $2 }' "$TMP/counts")"
[ -n "$USERS" ] || fail "the restored database has no users table"
[ "$USERS" -gt 0 ] || fail "users is empty after the restore"
[ -n "$ALEMBIC" ] || fail "the restored database has no alembic_version table"
[ "$ALEMBIC" = 1 ] || fail "alembic_version has $ALEMBIC rows, expected exactly 1"

# --- uploads ---
# Listed, not extracted: a listing reads the whole gzip stream without needing room for
# the files. backup.sh archives with `-C /from .`, so entries start with ./.
tar -tzf "$UP_FILE" > "$TMP/archive.list" \
  || fail "uploads archive $UP_NAME is unreadable"
FILES="$(awk '!/\/$/ { n++ } END { print n + 0 }' "$TMP/archive.list")"
log "uploads archive $UP_NAME holds $FILES files"
[ -n "$UPLOAD_COLUMNS" ] || log "UPLOAD_COLUMNS is empty; no stored path checked"
for pair in $UPLOAD_COLUMNS; do
  table="${pair%%.*}"
  column="${pair#*.}"
  sql="SELECT count(*) FROM information_schema.columns WHERE table_schema = 'public'"
  sql+=" AND table_name = '$table' AND column_name = '$column'"
  found="$(query_scratch_database "$sql")" || fail "cannot look up $pair"
  if [ "$found" != 1 ]; then
    log "$pair: not in this dump's schema; skipped"
    continue
  fi
  sql="SELECT \"$column\" FROM public.\"$table\" WHERE \"$column\" <> '' LIMIT 1"
  stored="$(query_scratch_database "$sql")" || fail "cannot read $pair"
  if [ -z "$stored" ]; then
    log "$pair: no stored path; skipped"
    continue
  fi
  grep -Fxq -e "./$stored" -e "$stored" "$TMP/archive.list" \
    || fail "$pair names $stored, which $UP_NAME does not hold"
  log "$pair: $stored is in the archive"
done

log "SUCCESS: $DB_NAME restored (users=$USERS); $UP_NAME holds $FILES files"
