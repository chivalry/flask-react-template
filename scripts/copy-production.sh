#!/usr/bin/env bash
# Replace this staging clone's database and uploads with copies of production's, to
# rehearse a release against real rows. Run as root on the server, from inside the
# staging clone:
#   bash scripts/copy-production.sh [--yes]
#
# PRODUCTION_DIR in this clone's .env names the production clone. The script refuses
# unless this .env says APP_ENVIRONMENT=staging, production's .env deploys production,
# the two COMPOSE_PROJECT_NAME values differ, both stacks use the same POSTGRES_USER and
# POSTGRES_DB (so the copy keeps its owner), staging's installed nginx site asks for a
# password, and both uploads volumes exist. It asks before changing anything unless
# --yes is given.
#
# Production is only read: pg_dump runs while it serves, and its uploads volume is
# mounted read-only. Staging's backend stops for the copy and starts again however the
# script ends; its entrypoint then migrates the copy to staging's schema. The database
# is replaced in one transaction, so a failed copy leaves staging's as it was.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
cd "$REPO_DIR"

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

# get KEY FILE -> the last KEY= value in FILE, or nothing.
get() { grep -E "^$1=" "$2" 2>/dev/null | tail -1 | cut -d= -f2- || true; }

ASSUME_YES=0
while [ $# -gt 0 ]; do
  case "$1" in
    --yes) ASSUME_YES=1; shift ;;
    *) fail 'usage: bash scripts/copy-production.sh [--yes]' ;;
  esac
done

[ -f .env ] || fail "no .env in $REPO_DIR; set staging up first (ai/staging.md)."
ENVIRONMENT="$(get APP_ENVIRONMENT .env)"
[ "$ENVIRONMENT" = staging ] ||
  fail "$REPO_DIR/.env deploys ${ENVIRONMENT:-production};" \
    'only staging copies production.'
PRODUCTION_DIR="$(get PRODUCTION_DIR .env)"
[ -n "$PRODUCTION_DIR" ] || fail "PRODUCTION_DIR is empty in $REPO_DIR/.env."
PRODUCTION_ENV="$PRODUCTION_DIR/.env"
[ -f "$PRODUCTION_ENV" ] || fail "no .env in $PRODUCTION_DIR (PRODUCTION_DIR)."
PRODUCTION_ENVIRONMENT="$(get APP_ENVIRONMENT "$PRODUCTION_ENV")"
[ "${PRODUCTION_ENVIRONMENT:-production}" = production ] ||
  fail "$PRODUCTION_ENV deploys $PRODUCTION_ENVIRONMENT, not production."
PROJECT="$(get COMPOSE_PROJECT_NAME .env)"
PRODUCTION_PROJECT="$(get COMPOSE_PROJECT_NAME "$PRODUCTION_ENV")"
if [ -z "$PROJECT" ] || [ -z "$PRODUCTION_PROJECT" ] ||
  [ "$PROJECT" = "$PRODUCTION_PROJECT" ]; then
  fail 'staging and production need different COMPOSE_PROJECT_NAME values.'
fi
POSTGRES_USER="$(get POSTGRES_USER .env)"
POSTGRES_DB="$(get POSTGRES_DB .env)"
if [ -z "$POSTGRES_USER" ] || [ -z "$POSTGRES_DB" ] ||
  [ "$POSTGRES_USER" != "$(get POSTGRES_USER "$PRODUCTION_ENV")" ] ||
  [ "$POSTGRES_DB" != "$(get POSTGRES_DB "$PRODUCTION_ENV")" ]; then
  fail "POSTGRES_USER and POSTGRES_DB must match production's," \
    'so the copy keeps its owner.'
fi
BACKEND_PORT="$(get BACKEND_PORT .env)"
BACKEND_PORT="${BACKEND_PORT:-5000}"
PRODUCTION_UPLOADS="${PRODUCTION_PROJECT}_uploads_data"
UPLOADS="${PROJECT}_uploads_data"

# The copy holds every account's email and password hash, so staging's installed
# nginx site must ask for a password before the copy is made.
APP_NAME="$(get APP_NAME .env)"
[ -n "$APP_NAME" ] || fail "APP_NAME is empty in $REPO_DIR/.env."
SITE="/etc/nginx/sites-available/$APP_NAME"
grep -Eq '^[^#]*auth_basic_user_file[[:space:]]' "$SITE" 2>/dev/null ||
  fail "staging's nginx site ($SITE) asks for no password; set STAGING_HTPASSWD" \
    "and deploy staging first (ai/staging.md)."

# docker run -v would create a missing volume empty, so both must already exist.
for volume in "$PRODUCTION_UPLOADS" "$UPLOADS"; do
  docker volume inspect "$volume" >/dev/null 2>&1 ||
    fail "volume $volume does not exist; deploy both stacks first."
done

compose() {
  docker compose -f docker-compose.yml -f docker/docker-compose.prod.yml \
    --env-file .env "$@"
}
production_compose() {
  docker compose -f "$PRODUCTION_DIR/docker-compose.yml" \
    -f "$PRODUCTION_DIR/docker/docker-compose.prod.yml" --env-file "$PRODUCTION_ENV" "$@"
}

# Poll staging's health endpoint every 2 s for up to 2 minutes, as deploy.sh does.
wait_for_backend() {
  local attempt
  for attempt in $(seq 1 60); do
    if curl -fsS "http://127.0.0.1:$BACKEND_PORT/api/health" >/dev/null 2>&1; then
      return 0
    fi
    echo "   waiting for the backend ($attempt/60)..."
    sleep 2
  done
  echo "ERROR: staging's backend did not become healthy within 2 minutes. Recent log:"
  compose logs --tail 50 backend || true
  exit 1
}

echo "This replaces staging's database and uploads (project $PROJECT) with copies of"
echo "production's (project $PRODUCTION_PROJECT in $PRODUCTION_DIR)."
if [ "$ASSUME_YES" = 0 ]; then
  printf 'Continue? [y/N] '
  read -r answer || true
  case "$answer" in
    y | Y) ;;
    *) echo 'Nothing changed.'; exit 1 ;;
  esac
fi

# Runs inside staging's db container. pg_restore turns the dump into SQL first, so a
# truncated dump stops before psql runs, and psql replaces the public schema in one
# transaction, so any error leaves staging's database as it was. Dropping the schema,
# rather than pg_dump --clean, also removes tables only staging's newer migrations
# made; the backend's entrypoint makes them again from the copy.
RESTORE='set -e
sql=$(mktemp)
trap "rm -f $sql" EXIT
pg_restore --no-owner --file="$sql"
{
  echo "SET client_min_messages = warning;"
  echo "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
  cat "$sql"
} | psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" --single-transaction \
  --file=- -v ON_ERROR_STOP=1 --quiet --output=/dev/null'

echo "==> Stopping staging's backend..."
compose stop backend
# From here on, staging's backend starts again however the script ends.
trap 'compose start backend >/dev/null 2>&1 || true' EXIT

echo "==> Copying production's database into staging..."
production_compose exec -T db pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc |
  compose exec -T db sh -c "$RESTORE" ||
  fail "copying the database failed; staging's database is unchanged."

echo "==> Copying production's uploads into staging..."
docker run --rm -v "$PRODUCTION_UPLOADS:/from:ro" -v "$UPLOADS:/to" alpine \
  sh -c 'find /to -mindepth 1 -delete && cp -a /from/. /to/' ||
  fail "copying the uploads failed; staging holds production's database."

trap - EXIT
echo "==> Starting staging's backend; its entrypoint migrates the copy..."
compose start backend
wait_for_backend
echo "==> Staging now holds a copy of production."
