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
set -Eeuo pipefail

MODE=daily
COMPOSE_OVERRIDE=''
LABEL=''
usage_error() { echo "ERROR: $*" >&2; exit 2; }
while [ "$#" -gt 0 ]; do
  case "$1" in
    --pre-migration) MODE=pre-migration; shift ;;
    --compose-file)
      [ "$#" -ge 2 ] || usage_error '--compose-file needs a path.'
      COMPOSE_OVERRIDE=$2
      shift 2
      ;;
    --label)
      [ "$#" -ge 2 ] || usage_error '--label needs a value.'
      LABEL=$2
      shift 2
      ;;
    *) usage_error "Unknown option: $1" ;;
  esac
done
# The label becomes part of a file name.
[[ "$LABEL" =~ ^[A-Za-z0-9._-]*$ ]] ||
  usage_error '--label may contain only letters, digits, dots, underscores, and hyphens.'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
cd "$REPO_DIR"

get() { grep -E "^$1=" .env | tail -1 | cut -d= -f2- || true; }

# --compose-file wins, then BACKUP_COMPOSE_FILE from .env, then the server's override.
# Whether the file exists is checked once fail() can report it, below.
[ -n "$COMPOSE_OVERRIDE" ] || COMPOSE_OVERRIDE="$(get BACKUP_COMPOSE_FILE)"
COMPOSE_OVERRIDE="${COMPOSE_OVERRIDE:-docker/docker-compose.prod.yml}"

# APP_NAME locates the log, so it is checked before output is redirected there.
APP_NAME="$(get APP_NAME)"
if [ -z "$APP_NAME" ]; then
  echo "ERROR: APP_NAME is empty in $REPO_DIR/.env; cannot locate the log directory." >&2
  exit 1
fi

compose() {
  docker compose -f docker-compose.yml -f "$COMPOSE_OVERRIDE" --env-file .env "$@"
}
LOG_DIR="/var/log/$APP_NAME"
WORK_ROOT="/var/backups/$APP_NAME"
mkdir -p "$LOG_DIR" "$WORK_ROOT"
exec >>"$LOG_DIR/backup.log" 2>&1

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
log() { printf '%s [%s] %s\n' "$(date -u +%FT%TZ)" "$MODE" "$*"; }

# Every failure path routes through fail(), including the ERR trap below, so this is
# the single place alerting has to be wired. That depends on the `set -E` above:
# without errtrace the ERR trap is not inherited into functions, so an rclone failure
# inside push() or prune() would exit 1 with no FAILURE line and no alert. alert.sh
# always exits 0, and the || true is belt-and-braces: a broken notifier must never
# replace the real failure below it.
fail() {
  log "FAILURE: $*"
  bash "$SCRIPT_DIR/alert.sh" "$APP_NAME: $MODE backup FAILED" \
    "$* (host $(hostname)). Log: $LOG_DIR/backup.log" || true
  exit 1
}
trap 'fail "error at line $LINENO"' ERR

# Checked here rather than with the options: a bad BACKUP_COMPOSE_FILE on the timer's
# path must alert, not exit before there is a log.
[ -f "$COMPOSE_OVERRIDE" ] || fail "no Compose file at $COMPOSE_OVERRIDE" \
  "(--compose-file or BACKUP_COMPOSE_FILE)"

PG_USER="$(get POSTGRES_USER)"
PG_DB="$(get POSTGRES_DB)"
PROJECT="$(get COMPOSE_PROJECT_NAME)"
[ -n "$PROJECT" ] \
  || fail "COMPOSE_PROJECT_NAME is not set in .env (it names the uploads volume)"
BUCKET="$(get SPACES_BUCKET)"
PREFIX="$(get BACKUP_PREFIX)"; PREFIX="${PREFIX:-prod}"
RETAIN_DAILY="$(get RETAIN_DAILY)"; RETAIN_DAILY="${RETAIN_DAILY:-14}"
RETAIN_WEEKLY="$(get RETAIN_WEEKLY)"; RETAIN_WEEKLY="${RETAIN_WEEKLY:-8}"
RETAIN_MONTHLY="$(get RETAIN_MONTHLY)"; RETAIN_MONTHLY="${RETAIN_MONTHLY:-6}"
RETAIN_LOCAL_DAILY="$(get RETAIN_LOCAL_DAILY)"
RETAIN_LOCAL_DAILY="${RETAIN_LOCAL_DAILY:-7}"
# 0 would delete every copy, this run's included, and a leading zero reads as octal.
for count in "$RETAIN_DAILY" "$RETAIN_WEEKLY" "$RETAIN_MONTHLY" \
  "$RETAIN_LOCAL_DAILY"; do
  [[ "$count" =~ ^[1-9][0-9]*$ ]] \
    || fail "RETAIN_* counts must be whole numbers above 0 (got '$count')"
done
UPLOADS_VOLUME="${PROJECT}_uploads_data"
REMOTE="spaces:${BUCKET}/${PREFIX}"

# Spaces is "ready" when a bucket is set and the rclone remote resolves.
spaces_ready() { [ -n "$BUCKET" ] && rclone lsd "spaces:${BUCKET}" >/dev/null 2>&1; }

# The remote counts as configured once SPACES_BUCKET is set and root's rclone config
# lists spaces:. Until then both modes keep their copies locally and warn. grep reads to
# the end rather than quitting at the match (-q), which could kill rclone with SIGPIPE;
# pipefail would then read a configured remote as missing.
spaces_remote_configured() {
  [ -n "$BUCKET" ] && rclone listremotes 2>/dev/null | grep -x 'spaces:' >/dev/null
}

# Keep the newest <count> files in <directory> whose names match <pattern>. Timestamped
# names sort chronologically, so a name sort is a time sort.
keep_newest_local_files() {  # <directory> <pattern> <count>
  find "$1" -maxdepth 1 -name "$2" -print0 \
    | sort -z -r | tail -z -n +"$(( $3 + 1 ))" | xargs -0 -r rm -f
}

AVAIL_KB="$(df -Pk "$WORK_ROOT" | awk 'NR==2 {print $4}')"
[ "$AVAIL_KB" -gt 2000000 ] || fail "less than ~2GB free on $WORK_ROOT"

TMP="$(mktemp -d "$WORK_ROOT/run.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT

# --- database dump (custom format, compressed) ---
DB_FILE="$TMP/db-$STAMP${LABEL:+-$LABEL}.dump"
compose exec -T db pg_dump -U "$PG_USER" -d "$PG_DB" -Fc > "$DB_FILE"
[ -s "$DB_FILE" ] || fail "empty database dump"

if [ "$MODE" = pre-migration ]; then
  mkdir -p "$WORK_ROOT/pre-migration"
  cp "$DB_FILE" "$WORK_ROOT/pre-migration/"
  keep_newest_local_files "$WORK_ROOT/pre-migration" 'db-*.dump' 3
  # The local dump above is the deploy's rollback safety net (always kept). Skip the
  # off-site push only while the rclone 'spaces:' remote isn't configured yet (first
  # deploy, before install-backup.sh). Once it IS configured, a failed push is a hard
  # error — never a silent local-only fallback.
  if ! spaces_remote_configured; then
    log "WARN: Spaces remote not configured yet; kept LOCAL pre-migration dump only"
  else
    rclone copyto "$DB_FILE" "$REMOTE/premigration/$(basename "$DB_FILE")" \
      || fail "Spaces push failed for pre-migration dump (remote configured, unreachable)"
    log "pre-migration backup OK (local + Spaces): $(basename "$DB_FILE")"
  fi
  exit 0
fi

# --- uploads archive (alpine volume-copy idiom) ---
# Guard first: `docker run -v <name>:...` would silently create a missing volume and
# archive it empty, reporting a false SUCCESS. Require the volume to already exist.
docker volume inspect "$UPLOADS_VOLUME" >/dev/null 2>&1 \
  || fail "uploads volume $UPLOADS_VOLUME not found (refusing to archive an empty volume)"
UP_FILE="$TMP/uploads-$STAMP.tar.gz"
docker run --rm -v "$UPLOADS_VOLUME":/from:ro -v "$TMP":/backup alpine \
  tar czf "/backup/uploads-$STAMP.tar.gz" -C /from .
[ -s "$UP_FILE" ] || fail "empty uploads archive"

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

# --- push to Spaces (daily always; weekly on Sunday; monthly on the 1st) ---
push() { rclone copyto "$1" "$REMOTE/$2/$3/$(basename "$1")"; }  # file tier kind
for pair in "$DB_FILE:db" "$UP_FILE:uploads"; do
  path="${pair%%:*}"; kind="${pair##*:}"
  push "$path" daily "$kind"
  if [ "$(date -u +%u)" = 7 ];  then push "$path" weekly "$kind";  fi
  if [ "$(date -u +%d)" = 01 ]; then push "$path" monthly "$kind"; fi
done

# --- retention: keep newest N per tier/kind (timestamp names sort chronologically) ---
prune() {  # remote-dir keep-count
  local dir="$1" keep="$2" listing files count drop i
  # Capture the listing on its own: a failure inside a process substitution never
  # reaches `set -e` or the ERR trap, so a broken listing would look like an empty
  # directory and skip retention while the run still reported SUCCESS.
  listing="$(rclone lsf --files-only "$dir")" || fail "rclone lsf failed for $dir"
  [ -n "$listing" ] || return 0
  mapfile -t files < <(printf '%s\n' "$listing" | sort)
  count="${#files[@]}"; drop=$(( count - keep ))
  [ "$drop" -gt 0 ] || return 0
  for (( i=0; i<drop; i++ )); do rclone deletefile "$dir/${files[$i]}"; done
  log "pruned $drop from $dir (kept $keep)"
}
for kind in db uploads; do
  prune "$REMOTE/daily/$kind"   "$RETAIN_DAILY"
  prune "$REMOTE/weekly/$kind"  "$RETAIN_WEEKLY"
  prune "$REMOTE/monthly/$kind" "$RETAIN_MONTHLY"
done

log "SUCCESS: $(basename "$DB_FILE") + $(basename "$UP_FILE") uploaded and pruned"
