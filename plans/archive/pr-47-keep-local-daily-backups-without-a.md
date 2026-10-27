# Issue #14: Keep local daily backups without a bucket and add a weekly restore drill

## Context

`scripts/backup.sh` refuses a daily run before dumping anything when no bucket is
configured (`backup.sh:106`), so a server without `SPACES_*` keeps only the dumps
deploys take, and `ai/backups.md:87-94` leaves a restore drill as a follow-up. This
change ports hukilau's local daily copies, `--compose-file`, and `--label` (commits
`58ba36f` and `55b7705`; hukilau's current `scripts/backup.sh` is the state after both,
with no later edits). It also builds a generic version of ranch-tracker's restore drill
(`ranch-tracker/staging/scripts/restore-drill.sh`), which restores into a scratch
container rather than a running staging database and reports failures through systemd.
No backend, frontend, migration, or CI workflow changes. `deploy.sh`,
`install-backup.sh`, and `provision.sh` have no tests yet. The shell-script convention
in `ai/conventions.md` requires a test for every changed script, so each gets one.

## Decisions

Settled during planning; do not revisit them.

- **Every deploy installs the backup and drill units.** Chuck chose this over the
  issue's "by `deploy.sh` ... when no bucket is configured". Taken literally, a server
  whose `.env` names a bucket but never ran `install-backup.sh` would get no backup
  timer at all, not even local copies. The acceptance criterion also needs
  `backup.service` on a server without a bucket, and `install-backup.sh` refuses to run
  without one. `install-backup.sh` still renders the same five units after verifying
  the bucket.
- **The drill fails on a dump more than 48 hours old.** Chuck chose this. The issue did
  not ask for it. Without it, a backup timer that stops is never reported, and the
  drill keeps passing on an old dump. The date arithmetic is pure bash, so the drill's
  test stays portable.
- **The drill is not ordered after the backup unit.** The planning question offered
  `After=<APP_NAME>-backup.service`, and it is dropped. `backup.service` is a oneshot
  with no timeout, so a hung backup would hold the drill's start job forever. A job
  that never starts never fails, so nothing would alert: that is exactly the case the
  48-hour check exists to catch. Hard links make concurrent runs safe instead.
  `backup.sh` links finished files into `daily/`, and the drill links its pair into its
  own directory. The cost: after two or more days of downtime spanning a Sunday 04:00,
  the catch-up drill at boot can start before the catch-up backup finishes and alert
  once about an old dump.
- **Alerts come only from `OnFailure=`, in the unit itself.** We own
  `restore-drill.service`; drop-ins are for units we don't own, like `certbot.service`.
  `restore-drill.sh`'s `fail()` logs and exits 1. Calling `alert.sh` there too would
  send two alerts per failure, since `OnFailure=` fires on every non-zero exit.
  `TimeoutStartSec=1h` turns a hung drill into a failure, because oneshot units have no
  start timeout by default.
- **Labels are the full commit SHA** checked out before `git pull`. hukilau's
  `deploy-lan.sh:476` labels with `git rev-parse HEAD`. That is the value #24's image
  tags will use to find a release's dump. The issue's `abc1234` only illustrates the
  flag.
- **Five changes to hukilau's `backup.sh`:**
    - The Compose-file existence check moves after `fail()` is defined, so a bad
      `BACKUP_COMPOSE_FILE` on the timer path alerts instead of exiting 2 before the
      log exists.
    - The SUCCESS line names the real files, labels included.
    - Daily copies are hard links rather than copies: complete the instant they
      appear, and no extra disk.
    - Every `RETAIN_*` must be a positive integer. `RETAIN_LOCAL_DAILY=0` would delete
      the run's own copy.
    - `spaces_remote_configured` reads with `grep -x … >/dev/null`, not `grep -qx`. An
      early grep exit can kill rclone with SIGPIPE, and `pipefail` would then read a
      configured remote as missing and silently skip the push.
- **Drill details beyond the issue's text:**
    - `--no-privileges` joins `--no-owner --exit-on-error`. The scratch cluster has one
      role, so a GRANT to any other role would stop the restore.
    - `docker rm -f -v` removes the anonymous data volume the image declares.
      Otherwise every drill would leak a restored database.
    - The archive is listed, not extracted.
    - `UPLOAD_COLUMNS` is a script constant, empty in the template, which stores no
      upload paths.
    - `DRILL_IMAGE` is pinned to the `db` service's image, and a test enforces it.
- **The backup timer stays at 02:30 UTC.** hukilau's noon Pacific is not ported.
- **Implementers:** Sonnet 5.5 group agents, per #27.

## Branch

`issue-14-keep-local-daily-backups-without-a`: already checked out; PR #47 exists.

## Change

**19 files.**

- **New (8):**
    - `scripts/restore-drill.sh` (mode 755)
    - `scripts/systemd/restore-drill.service`
    - `scripts/systemd/restore-drill.timer`
    - `scripts/systemd/alert-restore-drill.service`
    - `scripts/tests/test-restore-drill.sh`
    - `scripts/tests/test-deploy.sh`
    - `scripts/tests/test-install-backup.sh`
    - `scripts/tests/test-provision.sh`
- **Edited (11):**
    - `scripts/backup.sh`
    - `scripts/deploy.sh`
    - `scripts/install-backup.sh`
    - `scripts/provision.sh`
    - `scripts/systemd/backup.service`
    - `scripts/systemd/backup.timer`
    - `scripts/tests/test-backup.sh`
    - `.env.example`
    - `ai/backups.md`
    - `tools.md`
    - `README.md`

**Rules for every file:**

- Line numbers are those of `origin/main` at `f3b775c`, before any edit.
- Every line stays within 90 characters.
- Tests and units are mode 644; the new script is mode 755, like the others.
- Tests copy the helpers (`assert_contains`, `refute_contains`, `assert_file_count`)
  from `scripts/tests/test-backup.sh` verbatim.
- A test is bash-3.2-portable unless its section says otherwise. That means no
  `mapfile`, `${var,,}`, `sed -i`, `grep -P`, `tail -z`, `find -printf`, or `((n++))`.
- Each test checks that every stub shadows the real command, as `test-up.sh:39-43` does.

### scripts/systemd: three new units, two edited

`restore-drill.service` (new):

```ini
# Rendered by scripts/deploy.sh and scripts/install-backup.sh: __APP_NAME__ and
# __REPO_DIR__ come from the server's .env and clone location; installed as
# <APP_NAME>-restore-drill.service. A failed or timed-out drill starts
# <APP_NAME>-alert-restore-drill.service, which reports it through scripts/alert.sh.
[Unit]
Description=__APP_NAME__ weekly restore drill (newest daily backup -> scratch Postgres)
After=docker.service
Requires=docker.service
OnFailure=__APP_NAME__-alert-restore-drill.service

[Service]
Type=oneshot
WorkingDirectory=__REPO_DIR__
ExecStart=/bin/bash __REPO_DIR__/scripts/restore-drill.sh
# A oneshot unit has no start timeout by default, so a hung restore would never fail,
# never alert, and keep every later drill from starting.
TimeoutStartSec=1h
```

`restore-drill.timer` (new):

```ini
# Rendered by scripts/deploy.sh and scripts/install-backup.sh; installed as
# <APP_NAME>-restore-drill.timer.
[Unit]
Description=Weekly __APP_NAME__ restore drill

[Timer]
OnCalendar=Sun *-*-* 04:00:00 UTC
Persistent=true

[Install]
WantedBy=timers.target
```

`alert-restore-drill.service` (new), modelled on `alert-certbot.service`:

```ini
# Rendered by scripts/deploy.sh and scripts/install-backup.sh; installed as
# <APP_NAME>-alert-restore-drill.service and started by OnFailure= in
# restore-drill.service when a drill fails or times out.
[Unit]
Description=Report a failed restore drill for __APP_NAME__

[Service]
Type=oneshot
WorkingDirectory=__REPO_DIR__
ExecStart=/bin/bash __REPO_DIR__/scripts/alert.sh \
  "__APP_NAME__: restore drill FAILED" \
  "The restore drill failed on %H. Log: /var/log/__APP_NAME__/restore-drill.log"
```

`backup.service`:

- Lines 1-2 become:

    ```ini
    # Rendered by scripts/deploy.sh and scripts/install-backup.sh: __APP_NAME__ and
    # __REPO_DIR__ come from the server's .env and clone location; installed as
    # <APP_NAME>-backup.service.
    ```

- Line 4 becomes
  `Description=__APP_NAME__ backup (DB + uploads, local copies and an optional bucket)`.

`backup.timer`:

- Line 1 becomes the two-line comment
  `# Rendered by scripts/deploy.sh and scripts/install-backup.sh; installed as` /
  `# <APP_NAME>-backup.timer.`
- Line 3 becomes `Description=Daily __APP_NAME__ backup`.
- `OnCalendar` stays `*-*-* 02:30:00 UTC`.

### scripts/backup.sh — local daily copies, `--compose-file`, `--label`

The target is hukilau's `/Users/chuck/Projects/family/hukilau/scripts/backup.sh` with
the deviations listed under Decisions. Edit in place, top to bottom:

1. **Lines 1-10 (header)** become:

    ```bash
    #!/usr/bin/env bash
    # Back up the production database + uploads volume on this host and, once the rclone
    # remote 'spaces:' that install-backup.sh writes is configured, to an S3-compatible
    # bucket (DigitalOcean Spaces by default).
    #   backup.sh                 daily backup: DB dump + uploads archive, whose newest
    #                             RETAIN_LOCAL_DAILY copies stay in
    #                             /var/backups/<APP_NAME>/daily; pushed to Spaces with
    #                             tiered retention once the spaces: remote is configured.
    #   backup.sh --pre-migration DB-only dump kept locally (last 3) + pushed to
    #                             premigration/; used by deploy.sh before migrations.
    #   --compose-file FILE       Compose override applied over docker-compose.yml
    #                             (default BACKUP_COMPOSE_FILE from .env, then
    #                             docker/docker-compose.prod.yml).
    #   --label LABEL             names the dump db-<stamp>-<LABEL>.dump; deploy.sh passes
    #                             the commit that was running.
    # Reads config from the .env beside the repo. Logs to /var/log/<APP_NAME>/backup.log;
    # exits non-zero on any failure and reports it through scripts/alert.sh, so a broken
    # backup cannot fail silently the way an unwatched certbot renewal can. A malformed
    # command line exits 2 with a message on stderr, before anything is logged.
    ```

2. **Lines 13-16 (mode)** are replaced by hukilau's lines 22-44 verbatim: the
   `usage_error` parser for `--pre-migration`, `--compose-file`, and `--label`, then the
   label regex check.

3. **After line 22 (`get()`)**, insert:

    ```bash
    # --compose-file wins, then BACKUP_COMPOSE_FILE from .env, then the server's override.
    # Whether the file exists is checked once fail() can report it, below.
    [ -n "$COMPOSE_OVERRIDE" ] || COMPOSE_OVERRIDE="$(get BACKUP_COMPOSE_FILE)"
    COMPOSE_OVERRIDE="${COMPOSE_OVERRIDE:-docker/docker-compose.prod.yml}"
    ```

4. **Lines 31-34 (`compose()`):** the body becomes
   `docker compose -f docker-compose.yml -f "$COMPOSE_OVERRIDE" --env-file .env "$@"`.

5. **After line 55 (`trap … ERR`)**, insert:

    ```bash
    # Checked here rather than with the options: a bad BACKUP_COMPOSE_FILE on the timer's
    # path must alert, not exit before there is a log.
    [ -f "$COMPOSE_OVERRIDE" ] || fail "no Compose file at $COMPOSE_OVERRIDE" \
      "(--compose-file or BACKUP_COMPOSE_FILE)"
    ```

6. **After line 66 (`RETAIN_MONTHLY`)**, insert:

    ```bash
    RETAIN_LOCAL_DAILY="$(get RETAIN_LOCAL_DAILY)"
    RETAIN_LOCAL_DAILY="${RETAIN_LOCAL_DAILY:-7}"
    # 0 would delete every copy, this run's included, and a leading zero reads as octal.
    for count in "$RETAIN_DAILY" "$RETAIN_WEEKLY" "$RETAIN_MONTHLY" \
      "$RETAIN_LOCAL_DAILY"; do
      [[ "$count" =~ ^[1-9][0-9]*$ ]] \
        || fail "RETAIN_* counts must be whole numbers above 0 (got '$count')"
    done
    ```

7. **After line 71 (`spaces_ready`)**, insert hukilau's lines 108-119 with one change.
   In `spaces_remote_configured`, the pipeline reads
   `rclone listremotes 2>/dev/null | grep -x 'spaces:' >/dev/null`. Extend its comment
   with: "grep reads to the end rather than quitting at the match (-q), which could kill
   rclone with SIGPIPE; pipefail would then read a configured remote as missing."
   `keep_newest_local_files` is verbatim.

8. **Line 80** becomes `DB_FILE="$TMP/db-$STAMP${LABEL:+-$LABEL}.dump"`.

9. **Lines 84-103 (pre-migration block)** are replaced by hukilau's lines 132-148
   verbatim:
    - `cp "$DB_FILE" "$WORK_ROOT/pre-migration/"`
    - `keep_newest_local_files … 'db-*.dump' 3`
    - `if ! spaces_remote_configured`
    - `$(basename "$DB_FILE")` in the `copyto` target and in the OK log line

10. **Lines 105-106 (`# --- daily mode requires Spaces ---` and its check)** are
    deleted.

11. **After line 116 (`[ -s "$UP_FILE" ] || fail …`)**, insert:

    ```bash
    # --- local copies: the newest RETAIN_LOCAL_DAILY of each kind stay on this host ---
    # Hard links, not copies: each file is already complete, so it appears in daily/ whole
    # (the restore drill never reads half a file), and a run takes no extra disk for it.
    mkdir -p "$WORK_ROOT/daily"
    ln -f "$DB_FILE" "$UP_FILE" "$WORK_ROOT/daily/"
    keep_newest_local_files "$WORK_ROOT/daily" 'db-*.dump' "$RETAIN_LOCAL_DAILY"
    keep_newest_local_files "$WORK_ROOT/daily" 'uploads-*.tar.gz' "$RETAIN_LOCAL_DAILY"

    # Like --pre-migration: stay local until the remote exists. Once it is configured, an
    # unreachable bucket is a failure, never a silent local-only run.
    if ! spaces_remote_configured; then
      log "WARN: Spaces remote not configured; kept LOCAL daily backup only"
      exit 0
    fi
    spaces_ready || fail "Spaces not configured/reachable (SPACES_BUCKET + rclone remote)"
    ```

12. **Line 147** becomes
    `log "SUCCESS: $(basename "$DB_FILE") + $(basename "$UP_FILE") uploaded and pruned"`.

### scripts/restore-drill.sh — new, mode 755

Write exactly this. Keep it bash-3.2-compatible: its test runs on macOS too.

```bash
#!/usr/bin/env bash
# Weekly restore drill: prove the newest daily backup restores. It takes the newest
# daily/db dump and daily/uploads archive, from the bucket once the rclone remote
# 'spaces:' that install-backup.sh writes is configured and otherwise from
# /var/backups/<APP_NAME>/daily, restores the dump into a scratch Postgres container
# that has no network, and fails unless:
#   - the dump is at most MAX_AGE_HOURS old, so backups that stopped are reported;
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
UP_NAME="$(newest_matching_name "$TMP/uploads.list" \
  '^uploads-[0-9]{8}T[0-9]{6}Z.*\.tar\.gz$')"
[ -n "$DB_NAME" ] || fail "no daily database dump in $SOURCE"
[ -n "$UP_NAME" ] || fail "no daily uploads archive in $SOURCE"

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
```

Pitfalls this code already avoids; keep it that way:

- **Loop counters:** no `((n++))`. Bash 4.1+ under `set -e` exits when the result is 0,
  while bash 3.2 ignores it, so the test would pass on a Mac and fail in CI.
- **Counting:** no `grep -c`/`grep -vc` (exit 1 on zero matches fires ERR); count with
  awk.
- **`grep -q` in pipelines:** never `printf … | grep -q` under `pipefail`. Grep the
  file.

### scripts/deploy.sh — label the dump, install the backup and drill units

- **Lines 8-12 (header steps)** become:

    ```bash
    # Steps: pre-flight checks (Compose project + data volumes, certificate present),
    # git pull, pre-migration database backup named for the commit that was running
    # (starting the database first if the stack is stopped), rebuild and restart the
    # stack, wait for the backend to report healthy (its entrypoint runs the migrations
    # and the seed before gunicorn starts), install the nginx site, the certbot deploy
    # hook, and the systemd units: certificate monitoring, the daily backup, and the
    # weekly restore drill.
    ```

- **Before line 112 (`echo "==> Pulling latest code..."`)**, insert:

    ```bash
    # The commit checked out before the pull is the release whose schema the database
    # holds, unless an earlier deploy failed after pulling; the pre-migration dump is
    # named for it.
    RUNNING_COMMIT="$(git rev-parse HEAD)"
    ```

- **Line 124** becomes
  `if ! bash scripts/backup.sh --pre-migration --label "$RUNNING_COMMIT"; then`.
- **Lines 166-184** are replaced by the block below. The cert-check units join one
  render loop; there is one `daemon-reload` and one `enable --now`.

    ```bash
    # Host-wide certificate monitoring, the daily backup, and the weekly restore drill.
    # The unit files carry __APP_NAME__ and __REPO_DIR__ placeholders so several apps on
    # one host each get their own units; the certbot drop-in is named per app because
    # systemd merges OnFailure= across drop-ins. The backup and drill units go in on
    # every deploy, bucket or not: backup.sh keeps local copies until install-backup.sh
    # adds the remote.
    echo "==> Installing certificate monitoring, backups, and the restore drill..."
    render_systemd_unit() {  # <template> <destination>
      sed -e "s|__APP_NAME__|$APP_NAME|g" -e "s|__REPO_DIR__|$REPO_DIR|g" "$1" > "$2"
      chmod 644 "$2"
    }
    for unit in cert-check.service cert-check.timer alert-certbot.service \
      backup.service backup.timer restore-drill.service restore-drill.timer \
      alert-restore-drill.service; do
      render_systemd_unit "scripts/systemd/$unit" "/etc/systemd/system/$APP_NAME-$unit"
    done
    mkdir -p /etc/systemd/system/certbot.service.d
    render_systemd_unit scripts/systemd/certbot-onfailure.conf \
      "/etc/systemd/system/certbot.service.d/$APP_NAME-onfailure.conf"
    systemctl daemon-reload
    systemctl enable --now "$APP_NAME-cert-check.timer" "$APP_NAME-backup.timer" \
      "$APP_NAME-restore-drill.timer"
    ```

### scripts/install-backup.sh — render the drill units too; truthful failure text

- **Lines 2-6 (header)** become:

    ```bash
    # One-time (idempotent) installer for the off-site half of the backups. Installs
    # rclone, writes the rclone 'spaces:' remote from the server's .env, verifies the
    # bucket is readable and writable, then renders and enables the backup and
    # restore-drill units. deploy.sh renders the same units on every deploy, so local
    # backups and the drill run without a bucket; this adds the bucket. Run as root from
    # inside the clone, after filling SPACES_* in .env. Re-run after rotating Spaces keys
    # or editing the unit files.
    ```

- **Lines 54 and 59.** "timers were NOT enabled" becomes false once `deploy.sh`
  enables them, and the remote is written before the check. Replace each two-line
  message with:

    ```bash
      echo "       Fix SPACES_* and re-run; until then bucket pushes fail and alert," >&2
      echo "       and deploys stop at their pre-migration backup." >&2
    ```

  For the write probe, the first line becomes
  `Grant the key Read/Write and re-run; until then bucket pushes fail`, and the second
  `and alert, and deploys stop at their pre-migration backup.`
- **Lines 70-77** are replaced by:

    ```bash
    # deploy.sh renders these on every deploy too; rendering them here as well covers a
    # server whose last deploy predates them.
    for unit in backup.service backup.timer restore-drill.service restore-drill.timer \
      alert-restore-drill.service; do
      render_systemd_unit "scripts/systemd/$unit" "/etc/systemd/system/$APP_NAME-$unit"
    done
    systemctl daemon-reload
    systemctl enable --now "$APP_NAME-backup.timer" "$APP_NAME-restore-drill.timer"
    echo "==> Done. Run a backup now:  systemctl start $APP_NAME-backup.service"
    echo "    and then the drill:      systemctl start $APP_NAME-restore-drill.service"
    echo "    Logs: /var/log/$APP_NAME/backup.log, /var/log/$APP_NAME/restore-drill.log"
    ```

### scripts/provision.sh and .env.example — `RETAIN_LOCAL_DAILY`, `BACKUP_COMPOSE_FILE`

`provision.sh`:

- **Line 17** becomes
  `#   bash scripts/install-backup.sh                  # off-site copies, after SPACES_*`.
- **Lines 123-124** become the block below. The header line is 82 characters wide,
  like the others in the heredoc: 48 dashes after the title. `$APP_NAME` expands in the
  unquoted heredoc, so the generated `.env` carries the real path.

    ```text
    # --- Backups (scripts/backup.sh) ------------------------------------------------
    # Every daily run keeps its newest RETAIN_LOCAL_DAILY dumps and uploads archives in
    # /var/backups/$APP_NAME/daily. For off-site copies too, create a bucket and an
    # access key, fill in SPACES_*, and run scripts/install-backup.sh.
    ```

- **After line 133 (`RETAIN_MONTHLY=6`)**, add `RETAIN_LOCAL_DAILY=7`.

`.env.example`:

- **Lines 65-67** become:

    ```text
    # Operational alerts (scripts/alert.sh): failed backups and restore drills, failed
    # certbot renewals, certificates near expiry. Blank means log-only. Format is text
    # (ntfy.sh), slack, or discord.
    ```

- **Lines 71-72** become:

    ```text
    # Backups (scripts/backup.sh). Every daily run keeps its newest RETAIN_LOCAL_DAILY
    # database dumps and uploads archives in /var/backups/$APP_NAME/daily. To also push
    # them to an S3-compatible bucket via rclone, create the bucket and an access key,
    # fill in SPACES_*, and run scripts/install-backup.sh; RETAIN_DAILY, RETAIN_WEEKLY,
    # and RETAIN_MONTHLY count the bucket's copies.
    ```

- **After line 81**, add:

    ```text
    RETAIN_LOCAL_DAILY=7
    # Compose override scripts/backup.sh loads over docker-compose.yml; blank means
    # docker/docker-compose.prod.yml. backup.sh --compose-file wins over it.
    BACKUP_COMPOSE_FILE=
    ```

### scripts/tests/test-backup.sh — local copies, labels, overrides (stays Linux-only)

`backup.sh` still needs `mapfile` and GNU `tail -z`, so the `uname` guard and exit 77
stay.

**Header (lines 1-10):** also mention the local copies, labels, and Compose override.

**Setup, after line 22:** create the Compose files `backup.sh` now checks for:

```bash
mkdir -p "$TEST_DIR/repo/docker"
# backup.sh refuses a Compose override that does not exist; empty files will do.
for compose_file in docker-compose.yml docker/docker-compose.prod.yml \
  docker/docker-compose.alt.yml; do
  : > "$TEST_DIR/repo/$compose_file"
done
```

**New constants:**

- `DAILY="$TEST_DIR/backups/flask-react-template/daily"`
- `ALT_DUMP=' -f docker/docker-compose\.alt\.yml --env-file \.env exec -T db pg_dump '`

**New helper `expect_usage_error MESSAGE [ARGUMENT...]`.** It runs the copy with
stderr to `$TEST_DIR/stderr` and checks that:

- the exit status is exactly 2;
- MESSAGE is in stderr;
- `refute_contains . "$COMMANDS"` holds (nothing ran);
- `$LOG` does not exist.

**Cases.** Unlisted existing cases stay as they are.

1. **Replace lines 204-210 (no remote: local copies).**
    - Setup: `start_test_case`, then seed 8 older copies of each kind in `$DAILY`
      (`RETAIN_LOCAL_DAILY` unset, so the default 7 applies). `run_backup` must
      succeed.
    - Assert `$DUMP` and `$ARCHIVE` ran, and the log has
      `WARN: Spaces remote not configured; kept LOCAL daily backup only`.
    - Refute `'^rclone '`: an empty bucket skips even `listremotes`. Refute
      `'^alert\.sh '`.
    - File counts: `db-*.dump` 7, `uploads-*.tar.gz` 7, `db-2020*` 6,
      `uploads-2020*` 6, `*-2020010[12]T*` 0.
2. **New: `RETAIN_LOCAL_DAILY=2`** with 3 seeded of each. 2 of each remain; 1 of each
   is seeded.
3. **New: `SPACES_BUCKET=test-bucket` without the `remote-configured` flag.** The run
   succeeds with the WARN line, and both local copies are written. Assert
   `'^rclone listremotes'`; refute `'^rclone copyto'`.
4. **Lines 212-218 (unreachable remote).**
    - Keep the `rclone lsd` and `assert_failure_reported` checks.
    - Replace line 218's `refute_contains '^docker (volume|run) '`. Assert 1
      `db-*.dump` and 1 `uploads-*.tar.gz` in `$DAILY` (written before the push), and
      refute `'^rclone copyto'`.
5. **Lines 220-239 (remote reachable):** also assert 1 `db-*.dump` and 1
   `uploads-*.tar.gz` in `$DAILY`.
6. **Lines 261-267 (missing uploads volume).**
    - Drop `SPACES_BUCKET` and the `remote-configured` flag, so the default bucketless
      path reaches the archive step.
    - Keep the failure assertions, and add `assert_file_count 0 "$DAILY" '*'`.
7. **New: labels.**
    - **Pre-migration, local:** `run_backup --pre-migration --label abc1234`. Assert 1
      `db-*-abc1234.dump` in `$PRE_MIGRATION` and the pre-migration WARN line, and that
      `$DAILY` does not exist.
    - **Pre-migration, remote** (bucket and `remote-configured`):
        - `^rclone copyto .* $REMOTE/premigration/db-$STAMP-abc1234\.dump$`
        - `pre-migration backup OK \(local \+ Spaces\): db-$STAMP-abc1234\.dump`
        - 1 `db-*-abc1234.dump` in `$BUCKET_DIR/premigration`
    - **Retention:** 4 unlabelled seeded dumps plus a labelled run leave 3. One of them
      is `db-*-abc1234.dump`, and two are `db-2020*`.
    - **Daily, remote:** `run_backup --label nightly`.
        - 1 `db-*-nightly.dump` in `$DAILY`, and 1 in `$BUCKET_DIR/daily/db`.
        - The log has
          `SUCCESS: db-$STAMP-nightly\.dump \+ uploads-$STAMP\.tar\.gz uploaded`.
8. **New: usage errors**, each with `expect_usage_error`:
    - `'may contain only letters' --label 'a/b'`
    - `'--label needs a value' --label`
    - `'--compose-file needs a path' --compose-file`
    - `'Unknown option: --bogus' --bogus`
9. **New: the Compose override.**
    - `BACKUP_COMPOSE_FILE=docker/docker-compose.alt.yml`: assert `$ALT_DUMP`; refute
      `'docker-compose\.prod\.yml'`.
    - The same `.env` with `run_backup --compose-file docker/docker-compose.prod.yml`:
      assert `$DUMP`; refute `'docker-compose\.alt\.yml'`.
    - `BACKUP_COMPOSE_FILE=docker/missing.yml`:
      `assert_failure_reported daily 'no Compose file at docker/missing\.yml'`. Refute
      `'^docker '`.
10. **New: retention settings.**
    - `RETAIN_LOCAL_DAILY=0` fails with the reason below. Build it in a variable,
      `RETAIN_FAILURE='RETAIN_\* counts must be whole numbers above 0'`, then call
      `assert_failure_reported daily "$RETAIN_FAILURE \(got '0'\)"`.
    - `RETAIN_DAILY=08` fails the same way with `got '08'`.
    - In both cases, refute `'^docker '`.

### scripts/tests/test-restore-drill.sh — new, portable

**Header:** "Exercise scripts/restore-drill.sh: the real script runs in a disposable
copy of the repository with stub docker, rclone, df, sleep, and date commands, and
docker's stub plays the scratch Postgres from fixture files. It runs under macOS's
bash 3.2 and on Linux."

**Setup:**

- **Copy.** `sed` rewrites `/var/backups` → `$TEST_DIR/backups` and `/var/log` →
  `$TEST_DIR/log`, writing to `$TEST_DIR/repo/scripts/restore-drill.sh`.
- **Second copy.** `restore-drill-with-uploads.sh`, in the same directory, also rewrites
  `s|^UPLOAD_COLUMNS=''$|UPLOAD_COLUMNS='photos.file_path receipts.photo'|`. A `grep -q`
  must confirm the rewrite took.
- **`alert.sh`.** A stand-in logs `alert.sh $*` to the command log, so any direct call
  shows up.
- **Uploads source.** `$TEST_DIR/uploads-source` holds `photos/a.jpg` and `b.png`.
- **Fixture timestamps.** `NEWEST=20261025T023000Z`, `NEWEST_EPOCH=1792895400`,
  `OLDER=20261024T023000Z`, and `CONTAINER=flask-react-template-restore-drill`.
- **Image pin, checked first.** Both values must be non-empty and equal, or the test
  fails naming both:
    - `sed -n '/^  db:$/,/^  [a-z]/s/^    image: *//p' "$REPO_DIR/docker-compose.yml"`
    - `sed -n 's/^DRILL_IMAGE=//p' "$REPO_DIR/scripts/restore-drill.sh"`

**Stubs.** `docker`, `rclone`, `df`, and `sleep` are symlinks to `mock-system`, which
logs `"$name $*"` and reads markers from `$TEST_DIR/flags`. The fixture database lives
in `$TEST_DIR/database/tables/<table>` (a row count) and
`$TEST_DIR/database/columns/<table>.<column>` (a stored value). The case logic:

```bash
case "$name" in
  df)     # as in test-backup.sh: ample space, or 1000 KB while flags/low-disk exists
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
                # sed pulls table_name and column_name out of $sql; answer 1 or 0
                ;;
              'SELECT "'*)  # sed pulls the column and table; cat the stored value
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
```

`date` is its own stub. For exactly `-u +%s` it prints `$TEST_DIR/flags/now`; every
other call does `exec "$REAL_DATE" "$@"`, unlogged, as in `test-backup.sh:108-116`.

**Helpers:**

- **`start_test_case [LINE...]`** empties backups, bucket, log, flags, database, and
  `restored.dump`, and starts a fresh command log. It writes
  `flags/now = NEWEST_EPOCH + 3600` and tables `alembic_version=1 users=2 widgets=3`.
  The `.env` is `APP_NAME=flask-react-template POSTGRES_USER=app POSTGRES_DB=app` plus
  the given lines.
- **`seed_backup_pair DB_DIRECTORY UPLOADS_DIRECTORY STAMP [DUMP_TEXT]`** writes
  `db-STAMP.dump` containing `PGDMP dump of STAMP` (or `DUMP_TEXT`). It also writes
  `uploads-STAMP.tar.gz` with
  `COPYFILE_DISABLE=1 tar czf … -C "$TEST_DIR/uploads-source" .`, which keeps macOS
  from adding `._` files.
- **`set_table_counts NAME=COUNT...`** and **`set_upload_column TABLE.COLUMN VALUE`**
  write fixture files.
- **`run_drill [SCRIPT]`** runs the copy and prints the log on failure.
- **`expect_drill_failure DESCRIPTION [SCRIPT]`** expects a failed run, with stderr in
  `$TEST_DIR/stderr`.
- **`assert_drill_failed REASON`** checks four things:
    - `FAILURE: REASON` is in the log;
    - there is no `SUCCESS`;
    - `'^alert\.sh '` is absent, since `OnFailure=` alerts instead;
    - the last `docker` line, if there is any, is `docker rm -f -v $CONTAINER`.
      Read it with `grep '^docker ' … | tail -n 1 || true`.

**Cases.** Local runs seed into `$DAILY`, which is
`$TEST_DIR/backups/flask-react-template/daily`, for both directories.

1. **Local, happy path.**
    - Setup: OLDER and NEWEST pairs, plus a stray `notes.txt`. `run_drill` must succeed.
    - The `docker` lines other than `psql` must equal, in order:
      `docker rm -f -v $CONTAINER`, `$RUN`,
      `docker exec $CONTAINER pg_isready -q -h 127.0.0.1 -U app -d app`, `$RESTORE`,
      and `docker rm -f -v $CONTAINER`. Compare with `diff -u`, as
      `test-entrypoint.sh:46-49` does. `$RUN` and `$RESTORE` are built at the top of the
      test, as shown at the end of this section.
    - `restored.dump` holds `PGDMP dump of $NEWEST`.
    - The log has `rows users=2`, `rows widgets=3`, `rows alembic_version=1`,
      `db-$NEWEST\.dump is 60 minutes old`, `holds 2 files`, and
      `UPLOAD_COLUMNS is empty`, plus
      `SUCCESS: db-$NEWEST\.dump restored \(users=2\); uploads-$NEWEST\.tar\.gz holds 2`.
    - No `rclone` or `alert.sh` call.
    - No `drill.*` directory remains.
    - `$DAILY` still holds both pairs.
2. **The bucket wins.**
    - Setup: `SPACES_BUCKET=test-bucket` and `remote-configured`. OLDER and NEWEST pairs
      go in `$BUCKET_DIR/daily/db` and `…/uploads`, with text `PGDMP bucket dump`. A
      newer local pair `20261025T120000Z` has text `PGDMP local dump`.
    - Assert
      `^rclone copyto spaces:test-bucket/prod/daily/db/db-$NEWEST\.dump .*/drill\.`,
      and the same for uploads.
    - `restored.dump` holds `PGDMP bucket dump`.
    - The log names `from spaces:test-bucket/prod/daily`.
3. **Unreachable bucket:** `cannot list spaces:test-bucket/prod/daily/db`; no `docker`.
4. **Corrupted dump** (the acceptance criterion): with dump text `garbage`, the result
   is `pg_restore of db-$NEWEST\.dump failed`, and the container is removed.
5. **Sentinels.** The container is removed in every case.
    - `users=0` → `users is empty after the restore`
    - no `users` file → `the restored database has no users table`
    - `alembic_version=2` → `alembic_version has 2 rows, expected exactly 1`
    - no `alembic_version` file → `no alembic_version table`
6. **Nothing to restore.** No `docker` call in either case.
    - No `$DAILY` → `no daily backups yet`.
    - Dumps without archives → `no daily uploads archive in`.
7. **Freshness.**
    - `now = NEWEST_EPOCH + 47*3600` passes.
    - `+ 49*3600` fails with `db-$NEWEST\.dump is more than 48 hours old`, and the log
      has `is 2940 minutes old`; no `docker`.
    - A leap-day pair `20240229T120000Z`, seeded alone in a fresh case, with
      `now = 1709211600` logs `is 60 minutes old`. That is a check of the date
      arithmetic, which an off-by-a-day bug would fail.
8. **Readiness.**
    - `not-ready-count=2` passes, with exactly two `sleep 2` lines (count with
      `grep -c … || true`).
    - `never-ready` gives 60 `pg_isready` probes, 59 sleeps, `docker logs --tail 20`,
      and `did not accept connections within 2 minutes`. The container is removed.
9. **Unreadable archive.** Garbage in the `.tar.gz` gives
   `uploads archive uploads-$NEWEST\.tar\.gz is unreadable`.
10. **Upload columns** (`restore-drill-with-uploads.sh`):
    - `set_upload_column photos.file_path photos/a.jpg` →
      `photos.file_path: photos/a.jpg is in the archive`,
      `receipts.photo: not in this dump's schema; skipped`, and `SUCCESS`.
    - `photos/missing.jpg` → `photos.file_path names photos/missing.jpg, which`.
    - An empty value → `photos.file_path: no stored path; skipped`, and `SUCCESS`.
11. **Settings.** No `docker` call except where noted.
    - `low-disk` → `less than ~2GB free`.
    - `run-fails` → `cannot start a scratch container from postgres:16`, with the
      removal last.
    - `POSTGRES_DB=` → `POSTGRES_USER and POSTGRES_DB must be set`.
    - `APP_NAME=` → stderr `APP_NAME is empty`, and no command at all.

The two long calls case 1 expects:

```bash
RUN="docker run -d --name $CONTAINER --network none"
RUN+=' -e POSTGRES_HOST_AUTH_METHOD=trust -e POSTGRES_USER=app -e POSTGRES_DB=app'
RUN+=' postgres:16'
RESTORE="docker exec -i $CONTAINER pg_restore -U app -d app"
RESTORE+=' --no-owner --no-privileges --exit-on-error'
```

### scripts/tests/test-deploy.sh — new, portable

**Setup:**

- **Copy.** `sed` rewrites `/etc/letsencrypt` → `$TEST_DIR/letsencrypt`,
  `/etc/nginx` → `$TEST_DIR/nginx`, and `/etc/systemd/system` → `$TEST_DIR/systemd`,
  writing to `$TEST_DIR/repo/scripts/deploy.sh`.
- **Tripwire.** `refute_contains '/etc/'` on that copy, so no real host path survives.
  `/var/log` appears only in a message.
- **Files.** Copy `scripts/nginx-ssl.conf.template`, `scripts/letsencrypt-deploy-hook.sh`,
  and `scripts/systemd/` into the copy.
- **Directories.** Create `nginx/sites-available`, `nginx/sites-enabled/default`,
  `systemd/`, and `letsencrypt/live/example.com/fullchain.pem`.
- **`backup.sh`.** A stand-in in the copy logs `backup.sh $*`. It fails while
  `flags/backup-fails` exists.
- **`.env`.** `APP_NAME=flask-react-template`, `DOMAIN=example.com`,
  `PUBLIC_BASE_URL=https://example.com`, and
  `COMPOSE_PROJECT_NAME=flask-react-template`.

**Stubs:**

- **`docker`:**
    - `volume inspect <name>` succeeds while `flags/volume-<name>` exists.
    - Any call starting
      `compose -f docker-compose.yml -f docker/docker-compose.prod.yml --env-file .env`
      succeeds, except `exec -T db pg_isready` while `flags/db-down` exists.
    - Anything else is unexpected.
- **`git`:** `rev-parse HEAD` prints `COMMIT=0123456789abcdef0123456789abcdef01234567`,
  and `pull` succeeds. Any other call is unexpected.
- **`curl`:** exits 7 while `flags/backend-down` exists.
- **`nginx`:** fails while `flags/nginx-invalid` exists.
- **`systemctl` and `sleep`:** log only.
- **Real commands:** `sed`, `install`, `ln`, `mkdir`, and `seq`.

**Constants.** Build these with `+=` to stay within 90 characters:

```bash
COMPOSE='docker compose -f docker-compose.yml -f docker/docker-compose.prod.yml'
COMPOSE+=' --env-file .env'
TIMERS='flask-react-template-cert-check.timer flask-react-template-backup.timer'
TIMERS+=' flask-react-template-restore-drill.timer'
```

**Cases.** `expect_calls` is the `diff -u` helper from `test-entrypoint.sh`.

1. **Redeploy** (both `volume-*` flags). `expect_calls`:

    ```text
    docker volume inspect flask-react-template_postgres_data
    docker volume inspect flask-react-template_postgres_data
    docker volume inspect flask-react-template_uploads_data
    git rev-parse HEAD
    git pull
    $COMPOSE up -d db
    $COMPOSE exec -T db pg_isready
    backup.sh --pre-migration --label $COMMIT
    $COMPOSE down
    $COMPOSE up -d --build --remove-orphans
    curl -fsS http://127.0.0.1:5000/api/health
    systemctl enable nginx
    nginx -t
    systemctl reload-or-restart nginx
    systemctl daemon-reload
    systemctl enable --now $TIMERS
    ```

2. **Rendered files** (after case 1):
    - **Units.** All 8 `$TEST_DIR/systemd/flask-react-template-<unit>` files exist,
      plus `certbot.service.d/flask-react-template-onfailure.conf`. None contains
      `__[A-Z_]+__`, and `find "$TEST_DIR/systemd" -type f ! -perm 644` prints nothing.
    - **Exact lines.** Add `assert_line FILE LINE` (`grep -qxF -- "$2" "$1"`) and check:
        - `ExecStart=/bin/bash $TEST_DIR/repo/scripts/backup.sh`
        - `ExecStart=/bin/bash $TEST_DIR/repo/scripts/restore-drill.sh`
        - `OnFailure=flask-react-template-alert-restore-drill.service`
        - `TimeoutStartSec=1h`
        - `OnCalendar=Sun *-*-* 04:00:00 UTC`
        - `OnCalendar=*-*-* 02:30:00 UTC`
    - **Alert unit.** It names `flask-react-template: restore drill FAILED` and
      `/var/log/flask-react-template/restore-drill\.log`.
    - **nginx.** The site under `nginx/sites-available` has `example\.com` and no
      placeholder. Its `sites-enabled` symlink exists, `default` is gone, and the
      renewal hook is executable.
3. **First deploy** (no volume flags). The expected calls lose `up -d db`, `pg_isready`,
   and `backup.sh`. The output has `First deploy: no database to back up yet`, and all
   8 units are still installed.
4. **`backup-fails`:** output `pre-migration backup failed`. The calls end at the
   `backup.sh` line: refute `down$`, `--build`, and `^systemctl`.
5. **No certificate:** output `no certificate at`; refute `^git` and
   `^docker compose`.
6. **Only the postgres volume:**
   `expected volume 'flask-react-template_uploads_data' missing`; refute `^git`.
7. **`backend-down`:**
    - output `backend did not become ready within 2 minutes`;
    - `$COMPOSE logs --tail 50 backend` was called;
    - 60 `sleep 2` lines;
    - refute `^nginx` and `^systemctl`.
8. **`nginx-invalid`:** fails after `nginx -t`; refute `reload-or-restart` and
   `daemon-reload`.
9. **Bad `.env`.** Each case below exits 1 with its `ERROR:` line and logs no command:
    - no `.env`
    - `APP_NAME=`
    - `DOMAIN=`
    - `PUBLIC_BASE_URL=`

### scripts/tests/test-install-backup.sh — new, portable

**Setup:**

- **Copy.** `sed` rewrites `/root/.config/rclone` → `$TEST_DIR/rclone`, `/var/log` →
  `$TEST_DIR/log`, `/var/backups` → `$TEST_DIR/backups`, and `/etc/systemd/system` →
  `$TEST_DIR/systemd`.
- **Tripwire.** `refute_contains '/(etc|root|var)/'` on the copy.
- **Units.** Copy `scripts/systemd/` and create `$TEST_DIR/systemd`.
- **`.env`.** `APP_NAME=flask-react-template`,
  `SPACES_ENDPOINT=https://nyc3.digitaloceanspaces.com`, `SPACES_REGION=nyc3`,
  `SPACES_BUCKET=test-bucket`, `SPACES_ACCESS_KEY_ID=test-key`, and
  `SPACES_SECRET_ACCESS_KEY=test-secret`.

**Stubs:**

- **`rclone`:**
    - `lsd` fails while `flags/unreadable` exists.
    - `rcat` runs `cat > /dev/null` first, then fails while `flags/unwritable` exists.
      Without the drain, `echo | rclone rcat` can die of SIGPIPE under `pipefail` and
      look unwritable.
    - `deletefile` succeeds.
- **`systemctl`:** logs only.
- **`apt-get`:** a tripwire that is refuted. The `rclone` stub on PATH means
  `command -v rclone` succeeds, so `apt-get` never runs.

**Cases:**

1. **Happy path.**
    - `expect_calls`:
        - `rclone lsd spaces:test-bucket`
        - `rclone rcat spaces:test-bucket/.install-write-probe`
        - `rclone deletefile spaces:test-bucket/.install-write-probe`
        - `systemctl daemon-reload`
        - `systemctl enable --now flask-react-template-backup.timer` followed by
          `flask-react-template-restore-drill.timer`
    - `rclone.conf` has `[spaces]`, `provider = DigitalOcean`,
      `access_key_id = test-key`, `secret_access_key = test-secret`, `region = nyc3`,
      and the endpoint.
    - `find … -perm 600` finds `rclone.conf`.
    - The five units are rendered, mode 644, with no placeholder left.
    - The log and backup directories exist.
    - The output names `restore-drill.service`.
2. **`SPACES_BUCKET=`:** exit 1 with `nothing to back up to`; no commands and no
   `rclone.conf`.
3. **`APP_NAME=`:** exit 1; no commands.
4. **`unreadable`:**
    - exit 1;
    - the only call is `rclone lsd`;
    - the output has `until then bucket pushes fail and alert`;
    - no units and no `systemctl`.
5. **`unwritable`:** exit 1; the calls are `lsd` then `rcat`, with no `deletefile`;
   no units.
6. **Re-run after a key change.** Change `SPACES_ACCESS_KEY_ID` and run again: the new
   key is in `rclone.conf`, and the old one is gone.

### scripts/tests/test-provision.sh — new, portable

**Setup:**

- **Clone.** The disposable clone is `$TEST_DIR/my-app`, so `APP_NAME` defaults to
  `my-app`.
- **Copy.** `sed` rewrites `/etc/os-release` → `$TEST_DIR/os-release`, which holds
  `VERSION_CODENAME=noble`, and `/var/run/reboot-required` →
  `$TEST_DIR/reboot-required`.
- **Environment.** `export USER=tester` and `unset APP_NAME`.

**Stubs:**

- **`sudo`:** logs `sudo $*` and never executes. For `tee` it runs
  `cat > "$TEST_DIR/apt-source"`, which drains stdin so the pipe cannot SIGPIPE, and
  keeps the line for assertions.
- **`dpkg`:** prints `amd64`.
- **`openssl rand -hex N`:** bumps a counter file and prints the counter digit 2N
  times, `printf "%0$(( $3 * 2 ))d\n" 0 | tr 0 "$count"`. The three calls give
  `PG_PASS` = 32 `1`s, `SECRET` = 64 `2`s, and `ADMIN_PASS` = 32 `3`s.
- **`sleep`:** logs only.
- **Tripwires.** `apt-get`, `curl`, `systemctl`, `usermod`, and `reboot` log
  `ran without sudo` and fail. provision.sh calls each of them only through `sudo`.

**Cases:**

1. **No argument:** non-zero exit; stderr has
   `usage: bash scripts/provision.sh <domain>`; no commands.
2. **`example.com`, fresh.**
    - `.env` is mode 600.
    - Keys: `^APP_NAME=my-app$`, `^COMPOSE_PROJECT_NAME=my-app$`,
      `^DOMAIN=example\.com$`, `^PUBLIC_BASE_URL=https://example\.com$`, and
      `^RETAIN_LOCAL_DAILY=7$`, plus the other `RETAIN_*` values and `^SPACES_BUCKET=$`.
    - Secrets: the three passwords as above, with
      `DATABASE_URL=postgresql://app:1{32}@db:5432/app`.
    - **Every key the generated `.env` sets has a `^KEY=` line in the real
      `.env.example`.** Loop over
      `sed -n 's/^\([A-Z_][A-Z0-9_]*\)=.*/\1/p' .env`. This is what catches a variable
      added to one file but not the other.
    - `apt-source` matches `$APT_SOURCE`, shown at the end of this section. The line
      continuations inside provision.sh's quoted string leave runs of spaces, hence
      the `+`.
    - The `grep '^sudo '` lines equal the expected sequence (`diff -u`), from
      `sudo apt-get update -qq` through `sudo systemctl start nginx`. It includes
      `sudo tee /etc/apt/sources.list.d/docker.list` and
      `sudo usermod -aG docker tester`.
    - There is no `sudo reboot`, and the output has `Log out and back in`.
3. **`APP_NAME=custom`** gives `^APP_NAME=custom$` and `^COMPOSE_PROJECT_NAME=custom$`.
4. **An existing `.env`** stays byte-identical (`cmp`). The output says
   `already exists`, and there is no `openssl` call.
5. **The reboot marker exists:** `sleep 5`, then `sudo reboot`, in that order. The
   output has `rebooting in 5 seconds`.

The Docker apt source case 2 expects:

```bash
APT_SOURCE='^deb \[arch=amd64 +signed-by=/etc/apt/keyrings/docker\.asc\] +'
APT_SOURCE+='https://download\.docker\.com/linux/ubuntu +noble stable$'
```

### ai/backups.md — local copies, labels, the drill

Every line stays within 90 characters, and fenced blocks inside numbered steps are
indented four spaces, as the file does now. Section by section:

- **Overview (lines 3-10)** becomes:

    ```markdown
    Production keeps two kinds of durable state on the server: the Postgres database
    (volume `<COMPOSE_PROJECT_NAME>_postgres_data`) and uploaded files (volume
    `<COMPOSE_PROJECT_NAME>_uploads_data`, served at `/uploads/...`). `scripts/backup.sh`,
    run nightly on a systemd timer, dumps the database and archives the uploads. It keeps
    the newest `RETAIN_LOCAL_DAILY` (7) of each on the server and, once a bucket is
    configured, also pushes them to an S3-compatible bucket (DigitalOcean Spaces by
    default). Every deploy also dumps the database before running migrations, and a
    weekly restore drill proves that the newest backup restores.
    ```

- **New section `## Local copies`**, after the names paragraph (line 14), before
  `## Spaces layout`. It has:
    - a `text` block listing `daily/db-<timestamp>.dump`,
      `daily/uploads-<timestamp>.tar.gz`, and
      `pre-migration/db-<timestamp>-<commit>.dump` under `/var/backups/$APP_NAME/`;
    - that `daily/` keeps the newest `RETAIN_LOCAL_DAILY` of each kind and
      `pre-migration/` the newest three;
    - that until the remote exists a daily run logs the `WARN: … kept LOCAL daily backup
      only` line and succeeds;
    - that local copies die with the server, so they stand in for a bucket only until
      one exists;
    - the disk cost (seven archives of a 3 GB uploads volume take 21 GB, so lower
      `RETAIN_LOCAL_DAILY` on a small disk), and that a run refuses to start with under
      about 2 GB free.
- **Environment variables (lines 33-50).** Add `RETAIN_LOCAL_DAILY=7` and
  `BACKUP_COMPOSE_FILE=` to the block. After it, add: "`BACKUP_COMPOSE_FILE` names the
  Compose override `backup.sh` loads over `docker-compose.yml`; blank means
  `docker/docker-compose.prod.yml`, and `backup.sh --compose-file <path>` wins over it."
- **`## One-time setup` (lines 52-59) becomes `## Setup`:**
    1. Local backups need no setup: `scripts/deploy.sh` installs and enables
       `$APP_NAME-backup.timer` and `$APP_NAME-restore-drill.timer` on every deploy.
    2. For off-site copies, create a bucket and key pair and fill the `SPACES_*`
       values.
    3. Run `install-backup.sh`. It installs rclone, writes the remote, verifies read and
       write, and renders and enables the same timers. From the next run, backups also
       go to the bucket, and the drill restores from it. If its check fails, the remote
       is already written, so every push to the bucket fails and alerts, and deploys
       stop at their pre-migration backup, until a re-run passes.
    4. Rotate keys by re-running it.
- **`## Manual backup and logs` (lines 61-65) becomes `## Manual runs and logs`:**
    - Backup: `systemctl start $APP_NAME-backup.service`; log
      `/var/log/$APP_NAME/backup.log`; daily at 02:30 UTC.
    - Drill: `systemctl start $APP_NAME-restore-drill.service`; log
      `/var/log/$APP_NAME/restore-drill.log`; Sundays at 04:00 UTC.
    - `systemctl list-timers "$APP_NAME-*"`, and `journalctl -u <unit>` for what systemd
      saw, such as a drill stopped by its one-hour timeout.
- **`## Pre-migration dumps` (lines 67-76).**
    - `deploy.sh` now runs `backup.sh --pre-migration --label <commit>`. `<commit>` is
      the full commit checked out before the deploy's `git pull`, which is the release
      whose schema the dump holds, unless an earlier deploy failed after pulling.
    - The dump is `db-<timestamp>-<commit>.dump`, and the commit in its name identifies
      the code that matches its schema.
    - Keep the rest: the newest three locally, the push to `premigration/`, a failure
      aborting the deploy, and the restore pointer.
- **`## Failure alerting` (lines 78-85).** Add a paragraph:
    - The drill never calls `alert.sh` itself.
    - `OnFailure=` in `restore-drill.service` starts
      `$APP_NAME-alert-restore-drill.service`, which calls it whenever a drill exits
      non-zero or passes its one-hour timeout.
    - The alert names the drill's log, which holds the reason.
    - A drill run with plain `bash` logs the same but alerts nobody.
- **`## Restore drill (follow-up)` (lines 87-94) becomes `## Restore drill`.**
  `$APP_NAME-restore-drill.timer` runs `scripts/restore-drill.sh` Sundays at 04:00 UTC,
  and at the next boot if the server was off then. A numbered list of what it does:
    1. It takes the newest pair from the bucket once the remote exists, otherwise from
       `daily/`.
    2. It fails on a dump more than 48 hours old: backups run daily, so an older dump
       means they stopped reaching where the drill looks.
    3. It starts the scratch `postgres:16` container `$APP_NAME-restore-drill`, with no
       network and production's `POSTGRES_USER` and `POSTGRES_DB`, and restores with
       `pg_restore --no-owner --no-privileges --exit-on-error`.
    4. It logs every table's row count and fails unless `users` has rows and
       `alembic_version` exactly one.
    5. It lists the archive end to end without extracting it, logs its file count, and
       checks one stored path per `UPLOAD_COLUMNS` column the schema has.
    6. It removes the container, its volume, and its files however it exits, and logs
       `SUCCESS` or the `FAILURE` reason.

  Then bullets:
    - A server with no accounts (no `ADMIN_EMAIL` at its first deploy) fails until one
      exists.
    - A drill before the first nightly backup fails with `no daily backups yet`.
    - After two or more days of downtime spanning a Sunday 04:00, the catch-up drill can
      start before the catch-up backup finishes and alert once about an old dump.
    - `UPLOAD_COLUMNS` at the top of the script is empty because the template stores no
      upload paths. Add `table.column` in the same change as the migration that creates
      such a column; a dump from before the migration skips it.
    - `DRILL_IMAGE` must match the `db` service's image, since `pg_restore` refuses
      dumps from a newer server. `scripts/tests/test-restore-drill.sh` enforces it.
- **`## Orphaned-volume cleanup` (lines 96-113).** Add one sentence after the
  introduction: the drill removes its own anonymous data volume (`docker rm -f -v`).
  A `$APP_NAME-restore-drill` container left by a drill killed outright is removed,
  with its volume, by the next drill.
- **Disaster-recovery step 1 (line 120):** "Fetch the chosen artifacts from the bucket,
  or take them from `/var/backups/$APP_NAME/daily/` if the server still has them:".

### tools.md — operations bullets

- **Line 216:** "stub commands such as `docker`, `lsof`, `rclone`, `systemctl`, and
  `sudo`, which log…". Re-wrap the paragraph.
- **Lines 250-251 (`postgres:16`).** Append: "The weekly restore drill restores the
  newest backup into a scratch container of the same image, and
  `test-restore-drill.sh` checks that the drill and the `db` service name the same tag."
- **Line 276:** "…installs the nginx site, the renewal hook, and the monitoring,
  backup, and restore-drill units."
- **Lines 289-292 (systemd)** become:
    - the nightly backup at 02:30 UTC, the weekly restore drill on Sundays at 04:00 UTC,
      and the daily certificate expiry check at 05:00 UTC;
    - the `OnFailure` units that report a failed certbot renewal and a failed or
      timed-out drill;
    - `scripts/deploy.sh` installs them all, and `install-backup.sh` installs the backup
      and drill units too;
    - keep the placeholder sentence.
- **Lines 293-295 (rclone):** "once a bucket is configured, pushes the backups to it…,
  and the restore drill fetches the newest pair from it. …"
- **Lines 296-298 (`pg_dump` and `pg_restore`):** the deploy's dump is "named for the
  commit that was running", and "the restore drill restores the newest daily dump into a
  scratch container every week".

### README.md — lines 280-285

```markdown
Then, from your machine, `DEPLOY_HOST=root@example.com npm run deploy`.
`scripts/deploy.sh` backs up the database before migrating, rebuilds the containers,
installs the nginx site, and enables certificate monitoring, nightly backups kept on the
server, and a weekly drill that restores the newest one. Once the `SPACES_*` variables
are filled in, `bash scripts/install-backup.sh` adds off-site copies in a bucket.
Failures alert through `ALERT_WEBHOOK_URL`; `ai/backups.md` and `ai/tls.md` cover
restores, alerts, and renewals.
```

## Parallelism

- **Must be sequential, first.** The five unit files (three new, two edited), written
  straight from this plan. `test-deploy.sh` and `test-install-backup.sh` assert their
  rendered content, so they must be final before groups B and C start.
- **Can be done in parallel** after the units. Each agent owns its script and its test,
  and no two agents touch the same file:
    - **A:** `backup.sh` + `test-backup.sh`. Verify it with the `debian:trixie`
      command in the test's header, since the test is Linux-only.
    - **B:** `restore-drill.sh` (`chmod 755`) + `test-restore-drill.sh`.
    - **C:** `deploy.sh` + `test-deploy.sh`.
    - **D:** `install-backup.sh` + `test-install-backup.sh`.
    - **E:** `provision.sh` + `.env.example` + `test-provision.sh`. They share an agent
      because the test checks `.env.example` against the generated `.env`.
    - **F:** `ai/backups.md`, `tools.md`, `README.md`, written from this plan.
- **Must be sequential, last.** The full verification below, once A-F are done.

## No other changes needed

- **CI:** `scripts/tests/run-all.sh` globs `scripts/tests/test-*.sh`, so the four new
  tests run in CI without a workflow change. CI's `CI=true` turns `test-backup.sh`'s
  skip on macOS into a failure, which is why it runs there.
- **Other scripts and units:**
    - `scripts/alert.sh`: the alert unit calls it as `alert-certbot.service` does.
    - `scripts/remote-deploy.sh`, `cert-check.sh`, and the cert-check units: no change
      beyond joining the render loop.
- **Docker and app code:** the Compose files are unchanged; the drill uses plain
  `docker run`. No backend, frontend, migration, or dependency changes.
- **Documentation outside the three files:**
    - `ai/project.md` and `ai/conventions.md` still describe `scripts/` and the
      shell-test rules correctly.
    - `tools.md` gains no new tool: postgres, rclone, and systemd are already listed.

## Follow-ups (not in this PR)

1. **Double alerts in `backup.sh`.** Its `set -E` lets the ERR trap fire inside a
   `$(...)` whose pipeline fails. The df guard at line 73 is one such place. `fail()`
   then alerts from the subshell, its FAILURE line is captured instead of logged, and
   the parent alerts again.
2. **`install-backup.sh` writes `rclone.conf` before verifying the bucket.** A failed
   check leaves a remote that fails every push and stops deploys. It should verify
   with a temporary config and install it only on success.
3. **`backup.service` has no `OnFailure=` or timeout.** A killed or hung backup reports
   nothing. The drill's 48-hour check now catches it within a week.

## Verification

1. **During implementation, targeted runs per group:**
    - `bash scripts/tests/test-restore-drill.sh`
    - `bash scripts/tests/test-deploy.sh`
    - `bash scripts/tests/test-install-backup.sh`
    - `bash scripts/tests/test-provision.sh`
    - `test-backup.sh` through the `debian:trixie` command in its header.
    - Also run the five tests in that container, to prove the portable ones under GNU
      tools:

        ```bash
        docker run --rm -v "$PWD:/repo" -w /repo debian:trixie bash -c \
          'for t in backup restore-drill deploy install-backup provision; do
             bash "scripts/tests/test-$t.sh" || exit 1; done'
        ```

2. **At the end, in parallel:**
    - `npm run test:scripts`: every syntax check passes and every test passes;
      `test-backup.sh` skips on macOS.
    - `npm run lint:md`
    - `npx prettier --check ai/backups.md tools.md README.md`
    - `npm run test`, `npm run lint`, and `npm run lint:py`. Nothing they cover changes,
      and they must stay green.
3. **Repository hygiene:**
    - `git diff --check origin/main...HEAD` is clean.
    - `git ls-files -s scripts/restore-drill.sh` shows `100755`.
    - Every new test and unit file is `100644`.
4. **On a server, after merge.** The first deploy that pulls this change still runs the
   old `deploy.sh` to the end, because bash keeps reading the file it opened. So the
   label and the new units start with the deploy after it.
    - **Without a bucket.** After that second deploy:
        - `systemctl list-timers "$APP_NAME-*"` lists the backup and drill timers.
        - `systemctl start $APP_NAME-backup.service` leaves a dump and an archive in
          `daily/`, logs the WARN line, and exits 0.
        - `systemctl start $APP_NAME-restore-drill.service` logs the row counts and
          `SUCCESS`.
        - `docker ps -a --filter name=restore-drill` and
          `docker volume ls -qf dangling=true` show nothing new.
    - **A corrupted dump.** Copy the newest archive under a newer stamp beside a
      random `head -c 2000 /dev/urandom` "dump". The drill fails and the webhook alert
      arrives. Then remove the two fake files.
    - **A configured but unreachable remote.** After `install-backup.sh`, point
      `SPACES_BUCKET` at a missing bucket. The daily run fails and alerts. Restore it.
    - **A labelled dump.** `bash scripts/backup.sh --pre-migration --label abc1234`
      leaves `pre-migration/db-<stamp>-abc1234.dump`.
