#!/usr/bin/env bash
# Exercise scripts/copy-production.sh: the real script runs in a disposable copy of a
# staging clone beside a production clone, with its /etc/nginx path redirected into the
# test directory, the real nginx template rendered as staging's installed site, and stub
# docker, curl, and sleep commands. It checks the commands of a copy and their order,
# the restore script handed to the database container, that the script asks before it
# changes anything, that staging's backend starts again however a copy ends, and each
# way the script refuses. It runs under macOS's bash 3.2 and on Linux in CI, so it
# avoids bash 4 features.
set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TEST_DIR=$(mktemp -d)
trap 'rm -rf "$TEST_DIR"' EXIT
mkdir -p "$TEST_DIR/bin" "$TEST_DIR/staging/scripts" "$TEST_DIR/production"
export TEST_DIR
export PATH="$TEST_DIR/bin:$PATH"
FLAGS="$TEST_DIR/flags"
STAGING_ENV="$TEST_DIR/staging/.env"
PRODUCTION="$TEST_DIR/production"
PRODUCTION_ENV="$PRODUCTION/.env"
NGINX_DIR="$TEST_DIR/nginx"
SITE="$NGINX_DIR/sites-available/app-staging"
COMMANDS="$TEST_DIR/commands"
OUTPUT="$TEST_DIR/output"
# A run that reads its answer without being given one must see the end of the input,
# not wait on a terminal.
exec < /dev/null

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

# Redirect the host's nginx directory into the test directory.
sed "s|/etc/nginx|$NGINX_DIR|g" "$REPO_DIR/scripts/copy-production.sh" \
  > "$TEST_DIR/staging/scripts/copy-production.sh"
# A host path the rewrite missed would send the script to the real /etc, so none may be
# left; $TEST_DIR is cut out first, so only text the rewrite left alone is checked.
sed "s|$TEST_DIR||g" "$TEST_DIR/staging/scripts/copy-production.sh" \
  > "$TEST_DIR/rewritten-copy-production.sh"
refute_contains '/etc/' "$TEST_DIR/rewritten-copy-production.sh"

# Each stub logs its call to $TEST_DIR/commands before it answers, on one line because
# the restore command carries a multi-line script, and reads its conditions from markers
# in $TEST_DIR/flags. docker finds a volume while volume-<name> exists; the production
# dump fails while dump-fails exists, and otherwise writes a stand-in dump; the restore
# reads all of its input into $TEST_DIR/restored, and fails while restore-fails exists;
# the uploads copy fails while uploads-fail exists; and any other Compose call succeeds.
# curl cannot reach the backend while backend-down exists; sleep only logs.
cat > "$TEST_DIR/bin/mock-command" <<'MOCK'
#!/usr/bin/env bash
set -eu
name=${0##*/}
flags="$TEST_DIR/flags"
printf '%s\n' "$(printf '%s' "$name $*" | tr '\n' ' ')" >> "$TEST_DIR/commands"
case "$name" in
  docker)
    case "$*" in
      'volume inspect '*) [ -f "$flags/volume-$3" ] || exit 1 ;;
      *' exec -T db pg_dump '*)
        [ ! -f "$flags/dump-fails" ] || exit 1
        echo 'PGDMP standing in for production' ;;
      *' exec -T db sh -c '*)
        cat > "$TEST_DIR/restored"   # drain stdin so the writer never gets SIGPIPE
        [ ! -f "$flags/restore-fails" ] || exit 1 ;;
      'run --rm '*) [ ! -f "$flags/uploads-fail" ] || exit 1 ;;
      'compose '*) ;;
      *) echo "Unexpected docker call: $*" >&2; exit 1 ;;
    esac
    ;;
  curl) [ ! -f "$flags/backend-down" ] || exit 7 ;;
  sleep) ;;
  *) echo "Unexpected mock command: $name" >&2; exit 1 ;;
esac
MOCK
chmod +x "$TEST_DIR/bin/mock-command"
# A stub that did not come first on PATH would let the script reach the real Docker.
for command in docker curl sleep; do
  ln -s mock-command "$TEST_DIR/bin/$command"
  [ "$(command -v "$command")" = "$TEST_DIR/bin/$command" ] ||
    { echo "The $command stub does not shadow the real command." >&2; exit 1; }
done

STAGING_COMPOSE='docker compose -f docker-compose.yml'
STAGING_COMPOSE+=' -f docker/docker-compose.prod.yml --env-file .env'
PRODUCTION_COMPOSE="docker compose -f $PRODUCTION/docker-compose.yml"
PRODUCTION_COMPOSE+=" -f $PRODUCTION/docker/docker-compose.prod.yml"
PRODUCTION_COMPOSE+=" --env-file $PRODUCTION/.env"
COPY='docker run --rm -v app_uploads_data:/from:ro'
COPY+=' -v app-staging_uploads_data:/to alpine sh -c'
COPY+=' find /to -mindepth 1 -delete && cp -a /from/. /to/'

# install_site LINE -> staging's installed nginx site is the real template with its
# basic-auth line replaced by LINE, as deploy.sh would render it. Nothing else is
# replaced, because the script's guard reads nothing else.
install_site() {
  mkdir -p "$NGINX_DIR/sites-available"
  sed "s|__BASIC_AUTH__|$1|g" "$REPO_DIR/scripts/nginx-ssl.conf.template" > "$SITE"
}

# start_test_case [STAGING-LINE...] -> a fresh start, so no case inherits another's
# changes: no flags, an empty command log, both uploads volumes present, a site that asks
# for a password, and both .env files rewritten. Production's holds the four lines the
# script compares, and a case that needs another value appends it afterwards, since the
# script reads the last matching line. Staging's holds what the script reads plus any
# given lines, which win the same way.
start_test_case() {
  rm -rf "$FLAGS" "$NGINX_DIR" "$TEST_DIR/restored"
  mkdir -p "$FLAGS"
  : > "$COMMANDS"
  printf '%s\n' APP_ENVIRONMENT=production COMPOSE_PROJECT_NAME=app POSTGRES_USER=app \
    POSTGRES_DB=app > "$PRODUCTION_ENV"
  printf '%s\n' APP_ENVIRONMENT=staging COMPOSE_PROJECT_NAME=app-staging \
    APP_NAME=app-staging "PRODUCTION_DIR=$PRODUCTION" POSTGRES_USER=app \
    POSTGRES_DB=app BACKEND_PORT=5001 "$@" > "$STAGING_ENV"
  touch "$FLAGS/volume-app_uploads_data" "$FLAGS/volume-app-staging_uploads_data"
  install_site 'auth_basic "app-staging"; auth_basic_user_file /x;'
}

# run_copy_script [ARG...] -> run the copy of copy-production.sh, which reads its answer
# from this function's standard input, and leave its output in $OUTPUT.
run_copy_script() {
  bash "$TEST_DIR/staging/scripts/copy-production.sh" "$@" > "$OUTPUT" 2>&1
}

# run_copy [ARG...] -> the run succeeds; show its output if it fails.
run_copy() {
  run_copy_script "$@" ||
    { echo 'copy-production.sh failed. Its output:' >&2; cat "$OUTPUT" >&2; exit 1; }
}

# expect_failure DESCRIPTION [ARG...] -> the run exits 1, as every refusal does.
expect_failure() {
  local status=0 description=$1
  shift
  run_copy_script "$@" || status=$?
  [ "$status" -eq 1 ] || {
    echo "Expected $description; copy-production.sh exited $status. Its output:" >&2
    cat "$OUTPUT" >&2
    exit 1
  }
}

# assert_no_commands -> no stub ran.
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

# assert_before FIRST SECOND -> the first line of $COMMANDS that contains the fixed string
# FIRST comes before the first line that contains SECOND. The dump and the restore are
# the two ends of one pipe, so their order in the log is not fixed, and the whole log is
# never compared.
assert_before() {
  local first second
  first=$(grep -nF -- "$1" "$COMMANDS" | head -n 1 | cut -d: -f1) || true
  second=$(grep -nF -- "$2" "$COMMANDS" | head -n 1 | cut -d: -f1) || true
  { [ -n "$first" ] && [ -n "$second" ] && [ "$first" -lt "$second" ]; } || {
    echo "Expected '$1' (line ${first:-none}) before '$2' (line ${second:-none}) in:" >&2
    cat "$COMMANDS" >&2
    exit 1
  }
}

# With --yes the copy stops staging's backend, pipes production's custom-format dump into
# a restore run inside staging's database container, copies the uploads with production's
# volume mounted read-only, starts the backend again, and waits for its health endpoint.
start_test_case
run_copy --yes
assert_contains 'Staging now holds a copy of production\.' "$OUTPUT"
assert_line "$COMMANDS" 'docker volume inspect app_uploads_data'
assert_line "$COMMANDS" 'docker volume inspect app-staging_uploads_data'
assert_line "$COMMANDS" "$STAGING_COMPOSE stop backend"
assert_line "$COMMANDS" "$PRODUCTION_COMPOSE exec -T db pg_dump -U app -d app -Fc"
assert_line "$COMMANDS" "$COPY"
assert_line "$COMMANDS" "$STAGING_COMPOSE start backend"
assert_line "$COMMANDS" 'curl -fsS http://127.0.0.1:5001/api/health'
# The restore replaces the whole public schema in one transaction, so a failure leaves
# staging's database as it was, and it stops at the first error.
grep -F -- 'exec -T db sh -c' "$COMMANDS" > "$TEST_DIR/restore-call" || true
assert_contains 'exec -T db sh -c' "$TEST_DIR/restore-call"
assert_contains 'pg_restore --no-owner --file=' "$TEST_DIR/restore-call"
assert_contains 'DROP SCHEMA public CASCADE; CREATE SCHEMA public;' \
  "$TEST_DIR/restore-call"
assert_contains '--single-transaction' "$TEST_DIR/restore-call"
assert_contains '--file=-' "$TEST_DIR/restore-call"
assert_contains 'ON_ERROR_STOP=1' "$TEST_DIR/restore-call"
# The restore received exactly what the dump wrote, so the two calls shared one pipe.
[ "$(cat "$TEST_DIR/restored")" = 'PGDMP standing in for production' ] ||
  { echo 'The restore did not receive the dump.' >&2; exit 1; }
assert_before 'stop backend' 'exec -T db pg_dump'
assert_before 'stop backend' 'exec -T db sh -c'
assert_before 'exec -T db pg_dump' 'docker run'
assert_before 'exec -T db sh -c' 'docker run'
assert_before 'docker run' 'start backend'
assert_before 'start backend' 'curl'

# Without --yes it asks first: an answer other than y, or no answer at all, changes
# nothing, while a y, even one sent without a final newline, goes ahead.
start_test_case
printf 'n\n' > "$TEST_DIR/answer"
expect_failure 'a refused answer to stop the copy' < "$TEST_DIR/answer"
assert_contains 'Nothing changed\.' "$OUTPUT"
refute_contains 'stop backend' "$COMMANDS"
expect_failure 'a missing answer to stop the copy' < /dev/null
assert_contains 'Nothing changed\.' "$OUTPUT"
refute_contains 'stop backend' "$COMMANDS"
printf y > "$TEST_DIR/answer"
run_copy < "$TEST_DIR/answer"
assert_contains 'stop backend' "$COMMANDS"

# Only a staging .env copies production: a blank, production, or any other
# APP_ENVIRONMENT stops the run before any command.
for environment in '' production qa; do
  start_test_case "APP_ENVIRONMENT=$environment"
  expect_failure "APP_ENVIRONMENT='$environment' to stop the copy" --yes
  assert_contains 'only staging copies production' "$OUTPUT"
  assert_no_commands
done

# PRODUCTION_DIR must name a directory with a .env.
start_test_case PRODUCTION_DIR=
expect_failure 'an empty PRODUCTION_DIR to stop the copy' --yes
assert_contains 'PRODUCTION_DIR is empty' "$OUTPUT"
assert_no_commands
mkdir "$TEST_DIR/no-env"
start_test_case "PRODUCTION_DIR=$TEST_DIR/no-env"
expect_failure 'a PRODUCTION_DIR without a .env to stop the copy' --yes
assert_contains 'no \.env in .* \(PRODUCTION_DIR\)' "$OUTPUT"
assert_no_commands

# The clone PRODUCTION_DIR names must itself deploy production.
start_test_case
echo 'APP_ENVIRONMENT=staging' >> "$PRODUCTION_ENV"
expect_failure 'a PRODUCTION_DIR that deploys staging to stop the copy' --yes
assert_contains 'deploys staging, not production' "$OUTPUT"
assert_no_commands

# A production .env without APP_ENVIRONMENT, as on a server provisioned before it
# existed, deploys production too: blank means production.
start_test_case
printf '%s\n' COMPOSE_PROJECT_NAME=app POSTGRES_USER=app POSTGRES_DB=app \
  > "$PRODUCTION_ENV"
run_copy --yes
assert_contains 'Staging now holds a copy of production\.' "$OUTPUT"

# The two stacks need different, non-blank Compose project names, or they would share
# their volumes.
for project in app ''; do
  start_test_case "COMPOSE_PROJECT_NAME=$project"
  expect_failure "COMPOSE_PROJECT_NAME='$project' to stop the copy" --yes
  assert_contains 'need different COMPOSE_PROJECT_NAME values' "$OUTPUT"
  assert_no_commands
done

# Both stacks must use production's database role and name, so the copy keeps its owner.
for line in POSTGRES_DB=other POSTGRES_USER=other; do
  start_test_case "$line"
  expect_failure "$line to stop the copy" --yes
  assert_contains "must match production's" "$OUTPUT"
  assert_no_commands
done

# A volume that is missing would be created empty by docker run, so the run stops before
# it stops the backend.
start_test_case
rm "$FLAGS/volume-app-staging_uploads_data"
expect_failure 'a missing uploads volume to stop the copy' --yes
assert_contains 'volume app-staging_uploads_data does not exist' "$OUTPUT"
refute_contains 'stop backend' "$COMMANDS"

# A failed dump and a failed restore both leave staging's database alone, copy no
# uploads, and start the backend again.
for flag in dump-fails restore-fails; do
  start_test_case
  touch "$FLAGS/$flag"
  expect_failure "$flag to stop the copy" --yes
  assert_contains "staging's database is unchanged" "$OUTPUT"
  refute_contains '^docker run' "$COMMANDS"
  assert_last_command "$STAGING_COMPOSE start backend"
done

# Failed uploads leave production's database in staging, and still start the backend.
start_test_case
touch "$FLAGS/uploads-fail"
expect_failure 'a failed uploads copy to stop the copy' --yes
assert_contains "staging holds production's database" "$OUTPUT"
assert_last_command "$STAGING_COMPOSE start backend"

# A backend that never reports healthy ends the run after 60 probes, 2 seconds apart,
# with the backend's recent log.
start_test_case
touch "$FLAGS/backend-down"
expect_failure 'a backend that never reports healthy to stop the copy' --yes
assert_contains 'did not become healthy within 2 minutes' "$OUTPUT"
assert_line "$COMMANDS" "$STAGING_COMPOSE logs --tail 50 backend"
assert_sleeps 60

# An argument the script does not know stops it before any command.
start_test_case
expect_failure 'an unknown argument to stop the copy' --bogus
assert_contains 'usage:' "$OUTPUT"
assert_no_commands

# The copy holds every account's password hash, so staging's installed nginx site must
# ask for a password: the template's line left blank, the directive only in a comment,
# or no site at all stops the run.
for line in '' '# auth_basic_user_file /x;'; do
  start_test_case
  install_site "$line"
  expect_failure "the site line '$line' to stop the copy" --yes
  assert_contains 'asks for no password' "$OUTPUT"
  assert_no_commands
done
rm "$SITE"
expect_failure 'a missing site to stop the copy' --yes
assert_contains 'asks for no password' "$OUTPUT"
assert_no_commands

echo 'copy-production.sh regression checks passed.'
