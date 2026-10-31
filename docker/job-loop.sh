#!/bin/sh
# Run one scheduled job daily inside the stack, for a host that cannot run the systemd
# job timers (ai/project.md, Scheduled Jobs). Nothing in the Compose files starts it.
#   sh docker/job-loop.sh <job> <HH:MM>
# Each pass sleeps until the next HH:MM UTC, then runs python -u -m src_back.jobs.<job>,
# unbuffered so its output reaches the container log as it prints. It reads the clock
# for every wait, so a restart keeps the schedule rather than starting a new 24-hour
# countdown. A failed run is retried every RETRY_SECONDS, and after ATTEMPTS failures in
# a row the script exits 1, so the container's restart policy and the platform's
# monitoring see it. TERM, which docker stop sends, ends a wait at once; a run in
# progress goes on until it exits or docker stop's grace period ends.
set -u

ATTEMPTS=3
RETRY_SECONDS=300

usage() {
  echo 'usage: sh docker/job-loop.sh <job> <HH:MM>' >&2
  exit 1
}

[ $# -eq 2 ] && [ -n "$1" ] || usage
# The digits are listed rather than ranged, since macOS's sh matches a range by locale.
case $2 in
  [01][0123456789]:[012345][0123456789] | 2[0123]:[012345][0123456789]) ;;
  *) usage ;;
esac
JOB=$1
HOUR=${2%:*}
MINUTE=${2#*:}

# A shell runs a trap only once its foreground command ends, so pause sleeps in the
# background and waits, which the trap interrupts.
trap 'exit 0' TERM
pause() {
  sleep "$1" &
  wait $!
}

# seconds_until_next_run -> the seconds from now until the next HH:MM UTC, a full day
# when it is HH:MM now, so a run that ends within its first second is not repeated. Unix
# time gives every day 86400 seconds, so each midnight UTC is a multiple of it.
seconds_until_next_run() {
  now=$(date -u +%s) || return 1
  run_at=$((now - now % 86400 + ${HOUR#0} * 3600 + ${MINUTE#0} * 60))
  [ "$run_at" -gt "$now" ] || run_at=$((run_at + 86400))
  echo $((run_at - now))
}

echo "job-loop: running $JOB daily at $2 UTC."
while :; do
  # Without a wait to sleep through, the loop would run the job back to back.
  seconds=$(seconds_until_next_run) || {
    echo 'job-loop: cannot compute the next run time; exiting.' >&2
    exit 1
  }
  pause "$seconds"
  attempt=1
  until python -u -m "src_back.jobs.$JOB"; do
    if [ "$attempt" -ge "$ATTEMPTS" ]; then
      echo "job-loop: $JOB failed $ATTEMPTS times in a row; exiting." >&2
      exit 1
    fi
    echo "job-loop: $JOB failed; retrying in $RETRY_SECONDS seconds." >&2
    attempt=$((attempt + 1))
    pause "$RETRY_SECONDS"
  done
done
