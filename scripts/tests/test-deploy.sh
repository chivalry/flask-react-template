#!/usr/bin/env bash
# Exercise scripts/deploy.sh: the real script runs in a disposable copy of the
# repository, with its /etc paths redirected into the test directory, stub docker, git,
# curl, nginx, systemctl, and sleep commands, and a stand-in scripts/backup.sh. It
# checks the commands of a redeploy and of a first deploy, the units and the nginx site
# they install, and each way the script stops. It runs under macOS's bash 3.2 and on
# Linux in CI, so it avoids bash 4 features.
set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TEST_DIR=$(mktemp -d)
trap 'rm -rf "$TEST_DIR"' EXIT
mkdir -p "$TEST_DIR/bin" "$TEST_DIR/repo/scripts"
COMMIT=0123456789abcdef0123456789abcdef01234567
export TEST_DIR COMMIT
export PATH="$TEST_DIR/bin:$PATH"
APP=flask-react-template
PG_VOLUME="${APP}_postgres_data"
UPLOADS_VOLUME="${APP}_uploads_data"
FLAGS="$TEST_DIR/flags"
ENV_FILE="$TEST_DIR/repo/.env"
COMMANDS="$TEST_DIR/commands"
OUTPUT="$TEST_DIR/output"
LETSENCRYPT_DIR="$TEST_DIR/letsencrypt"
NGINX_DIR="$TEST_DIR/nginx"
SYSTEMD_DIR="$TEST_DIR/systemd"

# A bare `! grep` never fails under set -e, so both checks exit explicitly.
assert_contains() {
  grep -Eq -- "$1" "$2" || { echo "Missing /$1/ in ${2##*/}" >&2; exit 1; }
}

refute_contains() {
  if grep -Eq -- "$1" "$2"; then echo "Unexpected /$1/ in ${2##*/}" >&2; exit 1; fi
}

# assert_line FILE LINE -> LINE is a whole line of FILE, compared as a fixed string.
assert_line() {
  grep -qxF -- "$2" "$1" || { echo "Missing the line '$2' in ${1##*/}" >&2; exit 1; }
}

# Redirect the host's certificate, nginx, and systemd directories into the test directory.
sed -e "s|/etc/letsencrypt|$LETSENCRYPT_DIR|g" -e "s|/etc/nginx|$NGINX_DIR|g" \
  -e "s|/etc/systemd/system|$SYSTEMD_DIR|g" \
  "$REPO_DIR/scripts/deploy.sh" > "$TEST_DIR/repo/scripts/deploy.sh"
# A host path the rewrite missed would send deploy.sh to the real /etc, so none may be
# left; $TEST_DIR is cut out first, so only text the rewrite left alone is checked.
sed "s|$TEST_DIR||g" "$TEST_DIR/repo/scripts/deploy.sh" > "$TEST_DIR/rewritten-deploy.sh"
refute_contains '/etc/' "$TEST_DIR/rewritten-deploy.sh"
cp "$REPO_DIR/scripts/nginx-ssl.conf.template" \
  "$REPO_DIR/scripts/letsencrypt-deploy-hook.sh" "$TEST_DIR/repo/scripts/"
cp -R "$REPO_DIR/scripts/systemd" "$TEST_DIR/repo/scripts/"

# Stand-in for scripts/backup.sh: logs its arguments and fails while the backup-fails
# flag exists.
cat > "$TEST_DIR/repo/scripts/backup.sh" <<'BACKUP'
#!/usr/bin/env bash
printf 'backup.sh %s\n' "$*" >> "$TEST_DIR/commands"
[ ! -f "$TEST_DIR/flags/backup-fails" ] || exit 1
BACKUP

# Each stub logs its call to $TEST_DIR/commands before it answers, so a refused call is
# logged too, and reads its conditions from markers in $TEST_DIR/flags. docker finds a
# volume while volume-<name> exists and fails the uploads chown while chown-fails
# exists, and accepts the Compose calls deploy.sh makes, but the database does not
# answer pg_isready while db-down exists; git reports $COMMIT as HEAD and pulls; curl
# cannot reach the backend while backend-down exists; nginx rejects the configuration
# while nginx-invalid exists; systemctl and sleep only log.
cat > "$TEST_DIR/bin/mock-command" <<'MOCK'
#!/usr/bin/env bash
set -eu
name=${0##*/}
flags="$TEST_DIR/flags"
printf '%s\n' "$name $*" >> "$TEST_DIR/commands"
case "$name" in
  docker)
    compose='compose -f docker-compose.yml -f docker/docker-compose.prod.yml'
    compose+=' --env-file .env'
    case "$*" in
      'volume inspect '*) [ -f "$flags/volume-$3" ] || exit 1 ;;
      "$compose exec -T db pg_isready") [ ! -f "$flags/db-down" ] || exit 1 ;;
      'run --rm -v '*) [ ! -f "$flags/chown-fails" ] || exit 1 ;;
      "$compose "*) ;;
      *) echo "Unexpected docker call: $*" >&2; exit 1 ;;
    esac
    ;;
  git)
    case "$*" in
      'rev-parse HEAD') echo "$COMMIT" ;;
      pull) ;;
      *) echo "Unexpected git call: $*" >&2; exit 1 ;;
    esac
    ;;
  curl) [ ! -f "$flags/backend-down" ] || exit 7 ;;
  nginx) [ ! -f "$flags/nginx-invalid" ] || exit 1 ;;
  systemctl | sleep) ;;
  *) echo "Unexpected mock command: $name" >&2; exit 1 ;;
esac
MOCK
chmod +x "$TEST_DIR/bin/mock-command"
# A stub that did not come first on PATH would let deploy.sh reach the real Docker, git,
# nginx, or systemd.
for command in docker git curl nginx systemctl sleep; do
  ln -s mock-command "$TEST_DIR/bin/$command"
  [ "$(command -v "$command")" = "$TEST_DIR/bin/$command" ] ||
    { echo "The $command stub does not shadow the real command." >&2; exit 1; }
done

COMPOSE='docker compose -f docker-compose.yml -f docker/docker-compose.prod.yml'
COMPOSE+=' --env-file .env'
TIMERS='flask-react-template-cert-check.timer flask-react-template-backup.timer'
TIMERS+=' flask-react-template-restore-drill.timer'

# deploy.sh hands the uploads volume to the uid the backend image runs as.
IMAGE_UID=$(sed -n 's/.*useradd .*--uid \([0-9][0-9]*\).*/\1/p' \
  "$REPO_DIR/docker/backend.Dockerfile")
[ -n "$IMAGE_UID" ] ||
  { echo 'docker/backend.Dockerfile gives useradd no --uid.' >&2; exit 1; }
assert_line "$REPO_DIR/scripts/deploy.sh" "BACKEND_UID=$IMAGE_UID"
CHOWN="docker run --rm -v $UPLOADS_VOLUME:/uploads alpine"
CHOWN+=" chown -R $IMAGE_UID:$IMAGE_UID /uploads"

# start_test_case [LINE...] -> a fresh start: the certificate, the stock nginx site, an
# empty systemd directory, no flags, an empty command log, and a .env holding what
# deploy.sh requires plus any given lines, which win because deploy.sh reads the last
# one.
start_test_case() {
  rm -rf "$LETSENCRYPT_DIR" "$NGINX_DIR" "$SYSTEMD_DIR" "$FLAGS"
  mkdir -p "$LETSENCRYPT_DIR/live/example.com" "$NGINX_DIR/sites-available" \
    "$NGINX_DIR/sites-enabled" "$SYSTEMD_DIR" "$FLAGS"
  touch "$LETSENCRYPT_DIR/live/example.com/fullchain.pem" \
    "$NGINX_DIR/sites-enabled/default"
  : > "$COMMANDS"
  printf '%s\n' "APP_NAME=$APP" DOMAIN=example.com PUBLIC_BASE_URL=https://example.com \
    "COMPOSE_PROJECT_NAME=$APP" "$@" > "$ENV_FILE"
}

# add_data_volumes -> docker finds both of the project's data volumes, as on a redeploy.
add_data_volumes() {
  touch "$FLAGS/volume-$PG_VOLUME" "$FLAGS/volume-$UPLOADS_VOLUME"
}

# run_deploy_script -> run the copy of deploy.sh and leave its output in $OUTPUT. The
# strict umask lets a file mode the script does not set itself show in the checks.
run_deploy_script() {
  (umask 077; bash "$TEST_DIR/repo/scripts/deploy.sh") > "$OUTPUT" 2>&1
}

# run_deploy -> the run succeeds; show its output if it fails.
run_deploy() {
  run_deploy_script ||
    { echo 'deploy.sh failed. Its output:' >&2; cat "$OUTPUT" >&2; exit 1; }
}

# expect_failure DESCRIPTION -> the run exits 1, as every refusal of deploy.sh does.
expect_failure() {
  local status=0
  run_deploy_script || status=$?
  [ "$status" -eq 1 ] || {
    echo "Expected $1; deploy.sh exited $status. Its output:" >&2
    cat "$OUTPUT" >&2
    exit 1
  }
}

# expect_calls LINE... -> the stubs ran exactly these lines, in this order.
expect_calls() {
  printf '%s\n' "$@" | diff -u - "$COMMANDS"
}

# assert_no_commands -> neither a stub nor the stand-in ran.
assert_no_commands() {
  [ ! -s "$COMMANDS" ] ||
    { echo 'Unexpected commands:' >&2; cat "$COMMANDS" >&2; exit 1; }
}

# assert_last_command LINE -> the last command logged is LINE.
assert_last_command() {
  [ "$(tail -n 1 "$COMMANDS")" = "$1" ] ||
    { echo "Expected the last command to be '$1' in:" >&2; cat "$COMMANDS" >&2; exit 1; }
}

# assert_sleeps COUNT -> the run slept for 2 seconds exactly COUNT times.
assert_sleeps() {
  local found
  found=$(grep -c '^sleep 2$' "$COMMANDS") || true
  [ "$found" -eq "$1" ] ||
    { echo "Expected $1 sleeps of 2 seconds, found $found" >&2; exit 1; }
}

# assert_units_installed -> the eight units and the certbot drop-in are installed with
# no placeholder left, and no installed file has a mode other than 644.
assert_units_installed() {
  local unit file
  for unit in cert-check.service cert-check.timer alert-certbot.service \
    backup.service backup.timer restore-drill.service restore-drill.timer \
    alert-restore-drill.service; do
    file="$SYSTEMD_DIR/$APP-$unit"
    [ -f "$file" ] || { echo "Missing the installed unit $APP-$unit" >&2; exit 1; }
    refute_contains '__[A-Z_]+__' "$file"
  done
  file="$SYSTEMD_DIR/certbot.service.d/$APP-onfailure.conf"
  [ -f "$file" ] || { echo 'Missing the installed certbot drop-in' >&2; exit 1; }
  refute_contains '__[A-Z_]+__' "$file"
  find "$SYSTEMD_DIR" -type f ! -perm 644 > "$TEST_DIR/wrong-modes"
  [ ! -s "$TEST_DIR/wrong-modes" ] || {
    echo 'Installed files with a mode other than 644:' >&2
    cat "$TEST_DIR/wrong-modes" >&2
    exit 1
  }
}

# A redeploy, with both data volumes present, starts the database for a pre-migration
# dump labelled with the commit read before the pull, hands the uploads volume to the
# backend's user, then rebuilds, waits for the backend, installs the nginx site and the
# renewal hook, and enables the three timers after one daemon-reload. Every call is
# listed, in order, so a step that moved or went missing shows.
start_test_case
add_data_volumes
run_deploy
expect_calls \
  "docker volume inspect $PG_VOLUME" \
  "docker volume inspect $PG_VOLUME" \
  "docker volume inspect $UPLOADS_VOLUME" \
  'git rev-parse HEAD' \
  'git pull' \
  "$COMPOSE up -d db" \
  "$COMPOSE exec -T db pg_isready" \
  "backup.sh --pre-migration --label $COMMIT" \
  "$CHOWN" \
  "$COMPOSE down" \
  "$COMPOSE up -d --build --remove-orphans" \
  'curl -fsS http://127.0.0.1:5000/api/health' \
  'systemctl enable nginx' \
  'nginx -t' \
  'systemctl reload-or-restart nginx' \
  'systemctl daemon-reload' \
  "systemctl enable --now $TIMERS"

# What that run installed: every unit with its placeholders filled and mode 644, the
# backup and drill units with the rendered paths, schedules, alert, and timeout, the
# nginx site in place of the stock one, and an executable renewal hook.
assert_units_installed
assert_line "$SYSTEMD_DIR/$APP-backup.service" \
  "ExecStart=/bin/bash $TEST_DIR/repo/scripts/backup.sh"
assert_line "$SYSTEMD_DIR/$APP-restore-drill.service" \
  "ExecStart=/bin/bash $TEST_DIR/repo/scripts/restore-drill.sh"
assert_line "$SYSTEMD_DIR/$APP-restore-drill.service" \
  "OnFailure=$APP-alert-restore-drill.service"
assert_line "$SYSTEMD_DIR/$APP-restore-drill.service" 'TimeoutStartSec=1h'
assert_line "$SYSTEMD_DIR/$APP-restore-drill.timer" 'OnCalendar=Sun *-*-* 04:00:00 UTC'
assert_line "$SYSTEMD_DIR/$APP-backup.timer" 'OnCalendar=*-*-* 02:30:00 UTC'
assert_contains "$APP: restore drill FAILED" \
  "$SYSTEMD_DIR/$APP-alert-restore-drill.service"
assert_contains "/var/log/$APP/restore-drill\.log" \
  "$SYSTEMD_DIR/$APP-alert-restore-drill.service"
assert_contains 'example\.com' "$NGINX_DIR/sites-available/$APP"
refute_contains '__[A-Z_]+__' "$NGINX_DIR/sites-available/$APP"
# The rate-limit zone is named for the app, so apps sharing the host count apart.
assert_contains "zone=$APP-auth:10m" "$NGINX_DIR/sites-available/$APP"
[ "$(readlink "$NGINX_DIR/sites-enabled/$APP")" = "$NGINX_DIR/sites-available/$APP" ] ||
  { echo "sites-enabled/$APP does not link to the installed site." >&2; exit 1; }
[ ! -e "$NGINX_DIR/sites-enabled/default" ] ||
  { echo 'The stock nginx site is still enabled.' >&2; exit 1; }
[ -x "$LETSENCRYPT_DIR/renewal-hooks/deploy/reload-nginx.sh" ] ||
  { echo 'The renewal hook is not executable.' >&2; exit 1; }

# A first deploy, with no data volumes yet, has no database to dump: it skips the
# database start, the readiness check, and the backup, and still installs every unit.
start_test_case
run_deploy
expect_calls \
  "docker volume inspect $PG_VOLUME" \
  "docker volume inspect $UPLOADS_VOLUME" \
  'git rev-parse HEAD' \
  'git pull' \
  "$COMPOSE down" \
  "$COMPOSE up -d --build --remove-orphans" \
  'curl -fsS http://127.0.0.1:5000/api/health' \
  'systemctl enable nginx' \
  'nginx -t' \
  'systemctl reload-or-restart nginx' \
  'systemctl daemon-reload' \
  "systemctl enable --now $TIMERS"
assert_contains 'First deploy: no database to back up yet' "$OUTPUT"
assert_units_installed

# A failed pre-migration backup stops the deploy before it takes the stack down.
start_test_case
add_data_volumes
touch "$FLAGS/backup-fails"
expect_failure 'a failed pre-migration backup to stop the deploy'
assert_contains 'pre-migration backup failed' "$OUTPUT"
assert_last_command "backup.sh --pre-migration --label $COMMIT"
refute_contains 'down$' "$COMMANDS"
refute_contains '--build' "$COMMANDS"
refute_contains '^systemctl' "$COMMANDS"

# A failed chown of the uploads volume stops the deploy before it takes the stack
# down, so the old stack keeps serving.
start_test_case
add_data_volumes
touch "$FLAGS/chown-fails"
expect_failure 'a failed chown of the uploads volume to stop the deploy'
assert_contains 'could not hand' "$OUTPUT"
assert_last_command "$CHOWN"
refute_contains 'down$' "$COMMANDS"
refute_contains '--build' "$COMMANDS"

# A missing certificate stops the deploy before it pulls or touches the stack.
start_test_case
add_data_volumes
rm "$LETSENCRYPT_DIR/live/example.com/fullchain.pem"
expect_failure 'a missing certificate to stop the deploy'
assert_contains 'no certificate at' "$OUTPUT"
refute_contains '^git ' "$COMMANDS"
refute_contains '^docker compose' "$COMMANDS"

# One data volume without the other stops the deploy before it pulls: Compose would
# create the missing volume empty.
start_test_case
touch "$FLAGS/volume-$PG_VOLUME"
expect_failure 'a missing uploads volume to stop the deploy'
assert_contains "expected volume '$UPLOADS_VOLUME' missing" "$OUTPUT"
refute_contains '^git ' "$COMMANDS"

# A backend that never reports healthy ends the deploy after 60 probes, 2 seconds apart,
# with the backend's recent log, before nginx or any unit is touched.
start_test_case
add_data_volumes
touch "$FLAGS/backend-down"
expect_failure 'a backend that never reports healthy to stop the deploy'
assert_contains 'backend did not become ready within 2 minutes' "$OUTPUT"
assert_line "$COMMANDS" "$COMPOSE logs --tail 50 backend"
assert_sleeps 60
refute_contains '^nginx' "$COMMANDS"
refute_contains '^systemctl' "$COMMANDS"

# A database that never answers pg_isready ends the deploy the same way, before the
# dump or any change to the stack.
start_test_case
add_data_volumes
touch "$FLAGS/db-down"
expect_failure 'a database that never answers to stop the deploy'
assert_contains 'database did not become ready within 2 minutes' "$OUTPUT"
assert_line "$COMMANDS" "$COMPOSE logs --tail 50 db"
assert_sleeps 60
refute_contains '^backup\.sh ' "$COMMANDS"
refute_contains 'down$' "$COMMANDS"
refute_contains '^systemctl' "$COMMANDS"

# An nginx configuration that fails nginx -t is never reloaded, and no unit follows it.
start_test_case
add_data_volumes
touch "$FLAGS/nginx-invalid"
expect_failure 'an invalid nginx configuration to stop the deploy'
assert_last_command 'nginx -t'
refute_contains 'reload-or-restart' "$COMMANDS"
refute_contains 'daemon-reload' "$COMMANDS"

# A missing .env, or one that leaves APP_NAME, DOMAIN, or PUBLIC_BASE_URL empty, stops
# the deploy with its error before any command runs.
start_test_case
rm "$ENV_FILE"
expect_failure 'a missing .env to stop the deploy'
assert_contains 'ERROR: \.env not found' "$OUTPUT"
assert_no_commands
for setting in APP_NAME DOMAIN PUBLIC_BASE_URL; do
  start_test_case "$setting="
  expect_failure "an empty $setting to stop the deploy"
  assert_contains "ERROR: $setting is empty" "$OUTPUT"
  assert_no_commands
done

# A .env that leaves COMPOSE_PROJECT_NAME empty stops the deploy before any command runs,
# since Compose would otherwise pick the data volumes' names itself. The script words
# this one "is not set", unlike the three above.
start_test_case COMPOSE_PROJECT_NAME=
expect_failure 'an empty COMPOSE_PROJECT_NAME to stop the deploy'
assert_contains 'ERROR: COMPOSE_PROJECT_NAME is not set' "$OUTPUT"
assert_no_commands

echo 'Deploy regression checks passed.'
