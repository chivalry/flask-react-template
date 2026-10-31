#!/usr/bin/env bash
# Exercise docker/job-loop.sh with stub date, sleep, and python commands: the wait it
# computes from the clock, a full day when the time is now; the wait for the next day
# after a run succeeds; the retries after a failed run and the exit after the third
# failure in a row; a TERM that ends the loop at once, mid-sleep; a clock that cannot be
# read; and the usage check. It runs under macOS's bash 3.2 and on Linux in CI, where sh
# is dash, as it is in the backend image.
set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TEST_DIR=$(mktemp -d)
trap 'rm -rf "$TEST_DIR"' EXIT
mkdir -p "$TEST_DIR/bin"
export TEST_DIR
export PATH="$TEST_DIR/bin:$PATH"
COMMANDS="$TEST_DIR/commands"
OUTPUT="$TEST_DIR/output"
CLOCK='date -u +%s'
JOB='python -u -m src_back.jobs.example'
# 2023-11-14 22:13:20 UTC.
NOW=1700000000

# Each stub logs its call to $TEST_DIR/commands. date prints the time in $TEST_DIR/now,
# and fails while $TEST_DIR/date-fails exists. The Nth python call exits with the status
# on line N of $TEST_DIR/results, 0 past its end. sleep returns at once, except the call
# that $TEST_DIR/stop-at counts to, which sends TERM to the loop and then holds for five
# seconds, as a long sleep would.
cat > "$TEST_DIR/bin/mock-command" <<'MOCK'
#!/usr/bin/env bash
set -eu
name=${0##*/}
printf '%s %s\n' "$name" "$*" >> "$TEST_DIR/commands"
calls=$(grep -c "^$name " "$TEST_DIR/commands") || true
case "$name" in
  date)
    [ ! -f "$TEST_DIR/date-fails" ] || exit 1
    cat "$TEST_DIR/now"
    ;;
  python)
    status=$(sed -n "${calls}p" "$TEST_DIR/results")
    exit "${status:-0}"
    ;;
  sleep)
    if [ "$calls" = "$(cat "$TEST_DIR/stop-at")" ]; then
      kill -TERM "$PPID"
      /bin/sleep 5
    fi
    ;;
esac
MOCK
chmod +x "$TEST_DIR/bin/mock-command"
# A stub that did not come first on PATH would let the loop sleep for hours or run a
# real job.
for command in date sleep python; do
  ln -s mock-command "$TEST_DIR/bin/$command"
  [ "$(command -v "$command")" = "$TEST_DIR/bin/$command" ] ||
    { echo "The $command stub does not shadow the real command." >&2; exit 1; }
done

# A bare `! grep` never fails under set -e, so the check exits explicitly.
assert_contains() {
  grep -Eq -- "$1" "$2" || { echo "Missing /$1/ in ${2##*/}" >&2; exit 1; }
}

# start_case NOW STOP_AT [STATUS...] -> a fresh run: the clock reads NOW, the STOP_AT-th
# sleep sends TERM (0 for none), python exits with each STATUS in turn, and the command
# log is empty.
start_case() {
  echo "$1" > "$TEST_DIR/now"
  echo "$2" > "$TEST_DIR/stop-at"
  shift 2
  printf '%s\n' "$@" > "$TEST_DIR/results"
  : > "$COMMANDS"
}

# run_loop [ARG...] -> run the loop with these arguments, leaving its output in $OUTPUT,
# its exit status in $STATUS, and the whole seconds it took in $ELAPSED.
run_loop() {
  local start=$SECONDS
  STATUS=0
  sh "$REPO_DIR/docker/job-loop.sh" "$@" > "$OUTPUT" 2>&1 || STATUS=$?
  ELAPSED=$((SECONDS - start))
}

# expect_status STATUS -> the run exited STATUS; show its output if not.
expect_status() {
  [ "$STATUS" -eq "$1" ] || {
    echo "Expected the loop to exit $1; it exited $STATUS. Its output:" >&2
    cat "$OUTPUT" >&2
    exit 1
  }
}

# expect_calls LINE... -> the stubs ran exactly these lines, in this order.
expect_calls() {
  printf '%s\n' "$@" | diff -u - "$COMMANDS"
}

# expect_usage [ARG...] -> the loop prints its usage and exits 1 before running anything;
# a loop that accepted the arguments would stop at the first sleep's TERM, not spin.
expect_usage() {
  start_case "$NOW" 1
  run_loop "$@"
  expect_status 1
  assert_contains '^usage: sh docker/job-loop\.sh <job> <HH:MM>$' "$OUTPUT"
  [ ! -s "$COMMANDS" ] ||
    { echo "Unexpected commands for '$*':" >&2; cat "$COMMANDS" >&2; exit 1; }
}

# The loop waits until the next HH:MM UTC: later today, or tomorrow once today's has
# passed. After a run succeeds it waits for the next day's, and the TERM sent during
# that wait ends it with status 0. 09:08 has the leading zeros the arithmetic strips.
for entry in '23:00 2800' '22:14 40' '22:13 86380' '00:00 6400' '09:08 39280' \
  '03:00 17200'; do
  at=${entry% *}
  seconds=${entry#* }
  start_case "$NOW" 2
  run_loop example "$at"
  expect_status 0
  expect_calls "$CLOCK" "sleep $seconds" "$JOB" "$CLOCK" "sleep $seconds"
done
assert_contains '^job-loop: running example daily at 03:00 UTC\.$' "$OUTPUT"

# At HH:MM:00 the next run is a full day away, so a run that ends within its first
# second does not start again.
start_case 1699999980 2
run_loop example 22:13
expect_status 0
expect_calls "$CLOCK" 'sleep 86400' "$JOB" "$CLOCK" 'sleep 86400'

# TERM ends the loop at once, even mid-sleep: the stub's sleep holds for five seconds
# after sending it, so a loop that slept in the foreground would take five.
start_case "$NOW" 1
run_loop example 03:00
expect_status 0
expect_calls "$CLOCK" 'sleep 17200'
[ "$ELAPSED" -lt 3 ] ||
  { echo "The loop took ${ELAPSED}s to stop on TERM." >&2; exit 1; }

# A failed run is retried every five minutes. A success ends the retries, and the third
# failure in a row in the next day's run exits 1 without a fourth attempt.
start_case "$NOW" 0 1 0 1 1 1
run_loop example 03:00
expect_status 1
expect_calls "$CLOCK" 'sleep 17200' "$JOB" 'sleep 300' "$JOB" \
  "$CLOCK" 'sleep 17200' "$JOB" 'sleep 300' "$JOB" 'sleep 300' "$JOB"
assert_contains '^job-loop: example failed; retrying in 300 seconds\.$' "$OUTPUT"
assert_contains '^job-loop: example failed 3 times in a row; exiting\.$' "$OUTPUT"

# A clock that cannot be read ends the loop with status 1 before any run, rather than
# running the job with no wait; a loop that went on would stop at the first sleep's TERM.
start_case "$NOW" 1
touch "$TEST_DIR/date-fails"
run_loop example 03:00
rm "$TEST_DIR/date-fails"
expect_status 1
expect_calls "$CLOCK"
assert_contains '^job-loop: cannot compute the next run time; exiting\.$' "$OUTPUT"

# The job's name picks its module.
start_case "$NOW" 2
run_loop send_reminders 03:00
expect_status 0
expect_calls "$CLOCK" 'sleep 17200' 'python -u -m src_back.jobs.send_reminders' \
  "$CLOCK" 'sleep 17200'

# Anything but a job and an HH:MM time prints the usage before any command runs.
expect_usage
expect_usage example
expect_usage '' 03:00
expect_usage example 03:00 extra
for bad_time in 3:00 24:00 03:60 0300 03:0 ab:cd; do
  expect_usage example "$bad_time"
done

echo 'Job loop regression checks passed.'
