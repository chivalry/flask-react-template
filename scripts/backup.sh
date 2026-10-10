#!/usr/bin/env bash
# Off-site backup of the production database + uploads volume to an S3-compatible
# bucket (DigitalOcean Spaces by default) through the rclone remote 'spaces:' that
# install-backup.sh writes.
#   backup.sh                 daily backup (DB dump + uploads archive -> Spaces)
#   backup.sh --pre-migration DB-only dump kept locally (last 3) + pushed to
#                             premigration/; used by deploy.sh before migrations.
# Reads config from the .env beside the repo. Logs to /var/log/<APP_NAME>/backup.log;
# exits non-zero on any failure and reports it through scripts/alert.sh, so a broken
# backup cannot fail silently the way an unwatched certbot renewal can.
set -Eeuo pipefail

MODE=daily
if [ "${1:-}" = "--pre-migration" ]; then
  MODE=pre-migration
fi

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

compose() {
  docker compose -f docker-compose.yml -f docker/docker-compose.prod.yml \
    --env-file .env "$@"
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
UPLOADS_VOLUME="${PROJECT}_uploads_data"
REMOTE="spaces:${BUCKET}/${PREFIX}"

# Spaces is "ready" when a bucket is set and the rclone remote resolves.
spaces_ready() { [ -n "$BUCKET" ] && rclone lsd "spaces:${BUCKET}" >/dev/null 2>&1; }

AVAIL_KB="$(df -Pk "$WORK_ROOT" | awk 'NR==2 {print $4}')"
[ "$AVAIL_KB" -gt 2000000 ] || fail "less than ~2GB free on $WORK_ROOT"

TMP="$(mktemp -d "$WORK_ROOT/run.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT

# --- database dump (custom format, compressed) ---
DB_FILE="$TMP/db-$STAMP.dump"
compose exec -T db pg_dump -U "$PG_USER" -d "$PG_DB" -Fc > "$DB_FILE"
[ -s "$DB_FILE" ] || fail "empty database dump"

if [ "$MODE" = pre-migration ]; then
  mkdir -p "$WORK_ROOT/pre-migration"
  cp "$DB_FILE" "$WORK_ROOT/pre-migration/db-$STAMP.dump"
  # Keep the newest three. Timestamped names sort chronologically (prune() below relies
  # on the same property), so a name sort is a time sort.
  find "$WORK_ROOT/pre-migration" -maxdepth 1 -name 'db-*.dump' -print0 \
    | sort -z -r | tail -z -n +4 | xargs -0 -r rm -f
  # The local dump above is the deploy's rollback safety net (always kept). Skip the
  # off-site push only while the rclone 'spaces:' remote isn't configured yet (first
  # deploy, before install-backup.sh). Once it IS configured, a failed push is a hard
  # error — never a silent local-only fallback.
  if [ -z "$BUCKET" ] || ! rclone listremotes 2>/dev/null | grep -qx 'spaces:'; then
    log "WARN: Spaces remote not configured yet; kept LOCAL pre-migration dump only"
  else
    rclone copyto "$DB_FILE" "$REMOTE/premigration/db-$STAMP.dump" \
      || fail "Spaces push failed for pre-migration dump (remote configured, unreachable)"
    log "pre-migration backup OK (local + Spaces): db-$STAMP.dump"
  fi
  exit 0
fi

# --- daily mode requires Spaces ---
spaces_ready || fail "Spaces not configured/reachable (SPACES_BUCKET + rclone remote)"

# --- uploads archive (alpine volume-copy idiom) ---
# Guard first: `docker run -v <name>:...` would silently create a missing volume and
# archive it empty, reporting a false SUCCESS. Require the volume to already exist.
docker volume inspect "$UPLOADS_VOLUME" >/dev/null 2>&1 \
  || fail "uploads volume $UPLOADS_VOLUME not found (refusing to archive an empty volume)"
UP_FILE="$TMP/uploads-$STAMP.tar.gz"
docker run --rm -v "$UPLOADS_VOLUME":/from:ro -v "$TMP":/backup alpine \
  tar czf "/backup/uploads-$STAMP.tar.gz" -C /from .
[ -s "$UP_FILE" ] || fail "empty uploads archive"

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
  local dir="$1" keep="$2" files count drop i
  mapfile -t files < <(rclone lsf --files-only "$dir" 2>/dev/null | sort)
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

log "SUCCESS: db-$STAMP.dump + uploads-$STAMP.tar.gz uploaded and pruned"
