#!/usr/bin/env bash
# Render the development and production Compose configurations and check that only the
# development stack carries file watch, watchdog, and backend source owned by the app
# user, that every watched path exists and migrations sync without restarting the
# backend, that neither stack overrides the image's user, and what the production stack
# must keep: loopback-only ports and no database port; a backend that runs
# docker/entrypoint.sh under FLASK_ENV=production, where it starts gunicorn, with
# GUNICORN_WORKERS, secure session cookies, and the .env's APP_ENVIRONMENT passed
# through, blank when unset; and the nginx frontend. It needs the docker CLI with
# Compose, and jq, but no daemon; without them it exits 77, which
# scripts/tests/run-all.sh counts as a skip outside CI. It runs under macOS's bash 3.2
# and on Linux.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."
if ! docker compose version > /dev/null 2>&1 || ! command -v jq > /dev/null; then
  echo 'test-compose-config.sh needs the docker CLI with Compose, and jq.' >&2
  exit 77
fi
TEST_DIR=$(mktemp -d)
trap 'rm -rf "$TEST_DIR"' EXIT

# Placeholders for the variables the production override requires. An empty env file
# keeps a developer's .env out of the renders, and the shell must not supply the files
# or the values the checks read.
unset COMPOSE_FILE GUNICORN_WORKERS SESSION_COOKIE_SECURE SESSION_COOKIE_SAMESITE \
  APP_ENVIRONMENT
: > "$TEST_DIR/empty.env"
export POSTGRES_USER=app POSTGRES_PASSWORD=app POSTGRES_DB=app SECRET_KEY=placeholder \
  DATABASE_URL=postgresql://app:app@db:5432/app CORS_ALLOWED_ORIGINS=http://localhost \
  PUBLIC_BASE_URL=http://localhost

render() {
  docker compose --env-file "$TEST_DIR/empty.env" "$@" config --format json
}

render > "$TEST_DIR/dev.json"
render -f docker-compose.yml -f docker/docker-compose.prod.yml > "$TEST_DIR/prod.json"
(
  export GUNICORN_WORKERS=3
  render -f docker-compose.yml -f docker/docker-compose.prod.yml
) > "$TEST_DIR/prod-workers.json"
(
  export APP_ENVIRONMENT=staging
  render -f docker-compose.yml -f docker/docker-compose.prod.yml
) > "$TEST_DIR/prod-staging.json"

# check STACK FILTER EXPECTATION -> fail unless jq's FILTER holds for STACK's render.
check() {
  jq -e "$2" "$TEST_DIR/$1.json" > /dev/null || {
    echo "The $1 configuration should have $3." >&2
    exit 1
  }
}

check dev '.services.backend.environment.FLASK_ENV == "development"' \
  'a development backend'
check dev '.services.frontend.build.dockerfile == "docker/frontend.Dockerfile"' \
  'the Vite dev server as its frontend'
check dev '.services.backend.develop.watch | length > 0' 'backend file watch'
check dev '.services.frontend.develop.watch | length > 0' 'frontend file watch'
check dev '.services.backend.build.args.DEVELOPMENT_PACKAGES | test("^watchdog==")' \
  'watchdog in the backend build'
# File watch writes the synced files as the container's user, the app user.
check dev '.services.backend.build.args.SOURCE_OWNER == "app"' \
  'backend source owned by the app user'
# A restart runs the entrypoint's db upgrade, which would apply an unreviewed revision.
check dev '[.services.backend.develop.watch[] | select(.target == "/app/migrations")
  | .action] == ["sync"]' 'migrations synced without a restart'
# A watch path that does not exist, such as a renamed tsconfig file, watches nothing.
jq -r '.services[].develop.watch[]?.path' "$TEST_DIR/dev.json" > "$TEST_DIR/watch-paths"
while IFS= read -r path; do
  [ -e "$path" ] || { echo "The dev watch path $path does not exist." >&2; exit 1; }
done < "$TEST_DIR/watch-paths"
# A port without host_ip binds every interface, as 0.0.0.0 does. The count keeps the
# loopback check from passing on a stack that publishes nothing.
check prod '[.services[].ports[]?] | length > 0' 'published ports'
check prod '[.services[].ports[]? | .host_ip == "127.0.0.1"] | all' \
  'every published port bound to 127.0.0.1'
check prod '(.services.db.ports // []) | length == 0' 'no published database port'
check prod '.services.backend.environment.FLASK_ENV == "production"' \
  'a production backend'
# Under FLASK_ENV=production the entrypoint starts gunicorn (test-entrypoint.sh).
check prod '.services.backend.entrypoint == ["/bin/sh", "docker/entrypoint.sh"]' \
  'docker/entrypoint.sh as the backend entrypoint'
check prod '[.services[] | has("develop")] | any | not' 'no file watch'
check prod '(.services.backend.build.args.DEVELOPMENT_PACKAGES // "") == ""' \
  'no development packages in the backend build'
check prod '(.services.backend.build.args.SOURCE_OWNER // "") == ""' \
  'backend source left to root'
# The backend runs as the image's unprivileged user (docker/backend.Dockerfile).
for stack in dev prod; do
  check "$stack" '.services.backend | has("user") | not' \
    'no user override on the backend'
done
check prod '[.. | strings | select(test("--reload|flask run"))] | length == 0' \
  'no reload flag or development server command'
check prod '.services.backend.environment.GUNICORN_WORKERS == "4"' \
  'GUNICORN_WORKERS, 4 by default'
check prod-workers '.services.backend.environment.GUNICORN_WORKERS == "3"' \
  'the GUNICORN_WORKERS its .env gives'
check prod '.services.backend.environment.SESSION_COOKIE_SECURE == "true"' \
  'secure session cookies by default'
check prod '.services.backend.environment.SESSION_COOKIE_SAMESITE == "Strict"' \
  'strict SameSite session cookies by default'
check prod '.services.backend.environment.APP_ENVIRONMENT == ""' \
  'a blank APP_ENVIRONMENT, which the backend reads as production'
check prod-staging '.services.backend.environment.APP_ENVIRONMENT == "staging"' \
  'APP_ENVIRONMENT passed through to the backend'
check prod '.services.frontend.build.dockerfile == "docker/nginx.Dockerfile"' \
  'the nginx image as its frontend'

echo 'Compose configuration checks passed.'
