#!/usr/bin/env bash
# Render the development and production Compose configurations and check that only the
# development stack carries file watch, watchdog, and backend source owned by the app
# user, that every watched path exists and migrations sync without restarting the
# backend, that neither stack overrides the image's user, that both pass the .env's
# SMTP_*, OAUTH_GOOGLE_*, OAUTH_APPLE_*, and OAUTH_FACEBOOK_* variables to the backend,
# blank when unset, and Apple's private key, from a one-line value in the env file
# itself, with its line breaks, and what the production stack must keep: loopback-only
# ports and no database port; a backend that runs docker/entrypoint.sh under
# FLASK_ENV=production, where it starts gunicorn, with GUNICORN_WORKERS, secure session
# cookies, and the .env's APP_ENVIRONMENT passed through, blank when unset; and the
# nginx frontend. It needs the docker CLI with Compose, and jq, but no daemon; without
# them it exits 77, which scripts/tests/run-all.sh counts as a skip outside CI. It runs
# under macOS's bash 3.2 and on Linux.
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
  APP_ENVIRONMENT SMTP_HOST SMTP_PORT SMTP_SECURITY SMTP_USERNAME SMTP_PASSWORD \
  SMTP_FROM OAUTH_GOOGLE_CLIENT_ID OAUTH_GOOGLE_CLIENT_SECRET OAUTH_APPLE_CLIENT_ID \
  OAUTH_APPLE_TEAM_ID OAUTH_APPLE_KEY_ID OAUTH_APPLE_PRIVATE_KEY \
  OAUTH_FACEBOOK_CLIENT_ID OAUTH_FACEBOOK_CLIENT_SECRET
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

(
  export SMTP_HOST=smtp.example.com SMTP_PORT=2525 SMTP_SECURITY=ssl \
    SMTP_USERNAME=mailer@example.com SMTP_PASSWORD=app-password \
    SMTP_FROM=noreply@example.com
  render > "$TEST_DIR/dev-smtp.json"
  render -f docker-compose.yml -f docker/docker-compose.prod.yml \
    > "$TEST_DIR/prod-smtp.json"
)
(
  export OAUTH_GOOGLE_CLIENT_ID=google-id OAUTH_GOOGLE_CLIENT_SECRET=google-secret \
    OAUTH_APPLE_CLIENT_ID=com.example.web OAUTH_APPLE_TEAM_ID=TEAMID1234 \
    OAUTH_APPLE_KEY_ID=KEYID12345 OAUTH_APPLE_PRIVATE_KEY=apple-key \
    OAUTH_FACEBOOK_CLIENT_ID=facebook-id OAUTH_FACEBOOK_CLIENT_SECRET=facebook-secret
  render > "$TEST_DIR/dev-oauth.json"
  render -f docker-compose.yml -f docker/docker-compose.prod.yml \
    > "$TEST_DIR/prod-oauth.json"
)
# Compose reads this value from the env file, not the shell: one double-quoted line
# whose \n escapes it turns into line breaks. printf's %s keeps the backslashes.
pem='-----BEGIN PRIVATE KEY-----\nAAAA\n-----END PRIVATE KEY-----\n'
printf 'OAUTH_APPLE_PRIVATE_KEY="%s"\n' "$pem" > "$TEST_DIR/key.env"
# One line, as the runbook writes it; %b would turn the escapes into line breaks.
[ "$(grep -c '' "$TEST_DIR/key.env")" = 1 ] ||
  { echo 'The key.env value should be one line.' >&2; exit 1; }
render_key() {
  docker compose --env-file "$TEST_DIR/key.env" "$@" config --format json
}
render_key > "$TEST_DIR/dev-key.json"
render_key -f docker-compose.yml -f docker/docker-compose.prod.yml \
  > "$TEST_DIR/prod-key.json"

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

# Mail stays off until the .env names a host, and every SMTP_* value it gives reaches
# the backend in both stacks.
for stack in dev prod; do
  check "$stack" '.services.backend.environment | [.SMTP_HOST, .SMTP_PORT,
    .SMTP_SECURITY, .SMTP_USERNAME, .SMTP_PASSWORD, .SMTP_FROM] | all(. == "")' \
    'blank SMTP_* variables, which leave mail off'
  check "$stack-smtp" '.services.backend.environment | .SMTP_HOST == "smtp.example.com"
    and .SMTP_PORT == "2525" and .SMTP_SECURITY == "ssl"
    and .SMTP_USERNAME == "mailer@example.com" and .SMTP_PASSWORD == "app-password"
    and .SMTP_FROM == "noreply@example.com"' \
    'the SMTP_* variables its .env gives passed through to the backend'
  check "$stack" '.services.backend.environment | .OAUTH_GOOGLE_CLIENT_ID == ""
    and .OAUTH_GOOGLE_CLIENT_SECRET == ""' \
    'blank OAUTH_GOOGLE_* variables, which leave Google sign-in off'
  check "$stack-oauth" '.services.backend.environment
    | .OAUTH_GOOGLE_CLIENT_ID == "google-id"
    and .OAUTH_GOOGLE_CLIENT_SECRET == "google-secret"' \
    'the OAUTH_GOOGLE_* variables its .env gives passed through to the backend'
  check "$stack" '.services.backend.environment | [.OAUTH_APPLE_CLIENT_ID,
    .OAUTH_APPLE_TEAM_ID, .OAUTH_APPLE_KEY_ID, .OAUTH_APPLE_PRIVATE_KEY]
    | all(. == "")' \
    'blank OAUTH_APPLE_* variables, which leave Sign in with Apple off'
  check "$stack-oauth" '.services.backend.environment
    | .OAUTH_APPLE_CLIENT_ID == "com.example.web"
    and .OAUTH_APPLE_TEAM_ID == "TEAMID1234" and .OAUTH_APPLE_KEY_ID == "KEYID12345"
    and .OAUTH_APPLE_PRIVATE_KEY == "apple-key"' \
    'the OAUTH_APPLE_* variables its .env gives passed through to the backend'
  check "$stack" '.services.backend.environment | .OAUTH_FACEBOOK_CLIENT_ID == ""
    and .OAUTH_FACEBOOK_CLIENT_SECRET == ""' \
    'blank OAUTH_FACEBOOK_* variables, which leave Facebook sign-in off'
  check "$stack-oauth" '.services.backend.environment
    | .OAUTH_FACEBOOK_CLIENT_ID == "facebook-id"
    and .OAUTH_FACEBOOK_CLIENT_SECRET == "facebook-secret"' \
    'the OAUTH_FACEBOOK_* variables its .env gives passed through to the backend'
  check "$stack-key" '.services.backend.environment.OAUTH_APPLE_PRIVATE_KEY
    == "-----BEGIN PRIVATE KEY-----\nAAAA\n-----END PRIVATE KEY-----\n"' \
    'a one-line private key from its env file, with its line breaks'
done

check prod '.services.frontend.build.dockerfile == "docker/nginx.Dockerfile"' \
  'the nginx image as its frontend'

echo 'Compose configuration checks passed.'
