# Issue #23: Document and scaffold scheduled jobs without Celery

## Context

Two derived apps adopted Celery with Redis for one daily job each, and neither job ran
reliably. ranch-tracker's worker (`src_back/celery_worker.py:20`, `staging/` worktree at
922eaae) and ts-subscription-site's (`src_back/celery_worker.py:21`) never import the
modules that define their tasks: no `include=`, no `imports`, no `autodiscover_tasks`.
ranch-tracker's beat also keeps `celerybeat-schedule` in the container's writable layer
with an 86400-second interval, so every deploy restarts its countdown. Nothing in either
app enqueues work from a request. hukilau ran its reminders from a loop container
(`docker/reminders.sh` at `1a7fc99`) that slept a fixed 900 seconds after each attempt
and never exited non-zero, so nothing noticed a failure. The template offers no pattern,
so the next app chooses again. Decision recorded 2026-10-24: no Celery and no Redis.

An adversarial review ran the plan's Python through Ruff, Ruff format, pydoclint, the
function-length check, basedpyright, and pytest against the real `conftest.py` (3 tests,
`example.py` fully covered); replayed every loop case under dash and macOS sh; checked
`unit_lines` with BSD awk against the rendered unit; ran markdownlint and Prettier over
the edited documents; and rendered the documented loop service with
`docker compose config`. Its findings are folded in below. It could not run the shell
test files themselves, the `ubuntu:24.04` runs, `test-backend-image.sh`,
`systemd-analyze`, or PostgreSQL; Verification runs them.

Nothing in the template schedules work yet. What exists to build on:

- `scripts/deploy.sh:248-281` renders the production-only systemd units from
  `scripts/systemd/` with `render_systemd_unit` (`__APP_NAME__`, `__REPO_DIR__`), runs
  one `daemon-reload`, and enables three timers.
- `scripts/systemd/restore-drill.service` is the model: `Type=oneshot`, `OnFailure=` to
  its own alert unit, `TimeoutStartSec=1h`. `alert-restore-drill.service` calls
  `scripts/alert.sh "<subject>" "<body>"`.
- `src_back/seed.py:81-84` and `src_back/mailer.py:133-160,205-209` are the
  `python -m src_back.<module>` precedents; `pyproject.toml:60-64` already excludes
  `if __name__ == '__main__':` blocks from coverage.
- `src_back/mailer.py` is the first expected caller's tool: a job that sends mail calls
  `smtp_settings_from_environment()` and `send_email()`.

Two readings of the issue text:

- "an `OnFailure=` drop-in to the existing alert unit": each existing alert unit serves
  one service, so jobs get a templated `alert-job@.service` that calls the same
  `scripts/alert.sh`. `OnFailure=` sits in `job@.service` itself, as it does in
  `restore-drill.service`; a drop-in is needed only for a packaged unit such as
  `certbot.service`.
- `python -m src_back.jobs.example` "logs one line": the job prints it, as the seed does.
  `src_back/app.py:28` creates a logger but installs no handler or level, so
  `logging.info()` would print nothing.

Choices this plan makes:

- `main(app: Flask | None = None) -> int` builds the app with `create_app()` unless a
  test passes one, as the issue asks, and returns the exit status the way the mailer's
  `main()` does. An exception propagates, so the process exits 1 with its traceback in
  the journal.
- The example only reads: it counts the active accounts. Enabling its timer on a real
  server then changes nothing. It still commits, because the module is the one to copy,
  and a test spies on the commit so the pattern cannot lose it unnoticed.
- `job@.timer` runs daily at 03:00 UTC with `Persistent=true`: after the 02:30 backup has
  taken its dump, so a job that damages rows leaves that morning's backup untouched, and
  before the drill (Sundays 04:00) and the certificate check (05:00).
- The hour's limit is enforced inside the container, by `timeout 1h` in the command the
  unit execs. Stopping a `docker exec` client leaves its process running in the
  container (moby/moby#9098, open since 2014), so `TimeoutStartSec=` alone would report
  a timeout while the job ran on and overlapped the next day's run.
  `TimeoutStartSec=65min` stays as a backstop for a docker CLI that hangs, since a
  oneshot unit has no start timeout and a hung one keeps the timer from starting again.
- Jobs run as `python -u`. Under `exec -T` the job's stdout is a pipe, so Python
  buffers it, and a run that `timeout` stops would leave nothing in the journal for the
  alert's `journalctl` command to show.
- Only production installs the job units, as it does the backup units the issue names
  as the model: the `deploy.sh` header says the systemd units are production's alone,
  and `ai/staging.md` says a staging deploy changes only its own nginx site. A job is
  tried on staging by hand. The deploy enables no job timer; an operator does
  (`systemctl enable --now`), as the issue says.
- The loop script computes each wait from the clock, so a restart keeps the schedule,
  the property Celery's beat lacked. The wait is a full day when the time is HH:MM now,
  so a run that ends within its first second is not repeated. A failed run is retried
  every five minutes, and the third failure in a row exits 1, so a transient failure
  recovers within minutes and a persistent one shows as a container exit rather than a
  log line nobody reads. A wait that cannot be computed exits 1 rather than running the
  job back to back. It traps TERM and sleeps in the background, so `docker stop` ends a
  wait at once, even when the script runs as PID 1; a run in progress goes on until it
  exits or `docker stop`'s grace period ends.
- `test-backend-image.sh` checks that the production image has `timeout` and imports
  the jobs package, the two things the systemd unit's command needs from the image.

Decisions made with Chuck while planning, beyond the issue text:

- The loop alternative ships as a tested script, `docker/job-loop.sh` with
  `scripts/tests/test-job-loop.sh`, copied into the backend image. `ai/project.md` shows
  the Compose service to add, and no Compose file gains one.
- A project that keeps a job records it in the repository: its timer joins the
  `systemctl enable --now` call in `scripts/deploy.sh`, and a job that needs its own
  schedule gets `scripts/systemd/job@<name>.timer` in the deploy's unit list. Enabling a
  timer by hand stays the way to try a job.
- During implementation, the mutation pass found that a loop accepting an empty job name
  or `24:00` hung `test-job-loop.sh` instead of failing it, since `expect_usage` sent no
  TERM. Chuck approved letting its first sleep send TERM (`start_case "$NOW" 1`), so
  both regressions now fail in about a second.

## Branch

`issue-23-document-and-scaffold-scheduled-jobs` — already checked out; PR #53 exists.

## Change

**16 files**, 8 of them new: `src_back/jobs/__init__.py` (new),
`src_back/jobs/example.py` (new), `src_back/tests/test_example_job.py` (new),
`scripts/systemd/job@.service` (new), `scripts/systemd/job@.timer` (new),
`scripts/systemd/alert-job@.service` (new), `docker/job-loop.sh` (new),
`scripts/tests/test-job-loop.sh` (new), `scripts/deploy.sh`,
`scripts/tests/test-deploy.sh`, `scripts/tests/test-backend-image.sh`,
`docker/backend.Dockerfile`, `ai/project.md`, `ai/staging.md`, `tools.md`, `README.md`.

Line numbers are those of the files before any edit, so place each change by its quoted
neighbor. `docker/job-loop.sh` is mode 755, like `docker/entrypoint.sh`; the new test
and unit files are mode 644, like their neighbors. In Python, `npm run format:py` sets
the blank lines around top-level definitions.

### src_back/jobs/\_\_init\_\_.py — new

```python
"""Scheduled jobs: modules that ``python -m src_back.jobs.<name>`` runs once.

A job's ``main()`` builds the app with ``create_app()``, or takes one from a test, does
its work inside one application context, commits, prints one line saying what it did,
and returns the exit status. ``scripts/systemd/job@.service`` runs a job in the backend
container and its timer schedules it; ``ai/project.md`` describes both, and
:mod:`src_back.jobs.example` is the module to copy.
"""
```

### src_back/jobs/example.py — new

Import `create_app` at the top: the test replaces `example.create_app`, which an import
inside `main()` would bypass. `src_back.app` imports nothing from `src_back.jobs`, so
there is no cycle.

```python
"""Example job: count the accounts that can sign in.

``python -m src_back.jobs.example`` runs it once; on the server, enabling
``<APP_NAME>-job@example.timer`` runs it daily (``ai/project.md``, Scheduled Jobs). It
only reads, so enabling it changes nothing. A real job does its work where
:func:`_count_active_accounts` is called, and the commit after it saves that work in one
transaction; a job with an outside effect, such as an email, commits after each one
instead, so a failure later in the run neither repeats it nor loses the record of it.
"""

from flask import Flask

from src_back.app import create_app
from src_back.extensions import db
from src_back.models import User


def main(app: Flask | None = None) -> int:
    """Run the job once and print one line saying what it did.

    Args:
        app: The application to run against; ``None`` builds one with
            ``create_app()``, as ``python -m src_back.jobs.example`` does.

    Returns:
        ``0`` once the work is committed. An exception propagates instead, so the
        process exits 1, the systemd unit fails, and its alert fires.
    """
    if app is None:
        app = create_app()
    with app.app_context():
        active = _count_active_accounts()
        db.session.commit()
    print(f'Example job counted active accounts: {active}.')
    return 0


def _count_active_accounts() -> int:
    """Count the accounts that are not deactivated.

    Returns:
        The number of active accounts.
    """
    return db.session.query(User).filter_by(is_active=True).count()


if __name__ == '__main__':
    raise SystemExit(main())
```

### src_back/tests/test_example_job.py — new

`main(app)` pushes its own application context over the fixture's, so it gets a session
of its own, which sees the rows the fixtures committed, as `test_seed.py`'s calls do.

```python
import pytest
from flask import Flask
from flask_sqlalchemy import SQLAlchemy

from src_back.jobs import example
from src_back.models import User


def test_main_counts_the_active_accounts(
    app: Flask,
    user: User,
    admin_user: User,
    inactive_user: User,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert example.main(app) == 0
    assert capsys.readouterr().out == 'Example job counted active accounts: 2.\n'


def test_main_builds_the_app_when_none_is_given(
    app: Flask,
    user: User,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # python -m src_back.jobs.example passes no app; the test app stands in for the one
    # create_app() would build from the environment.
    monkeypatch.setattr(example, 'create_app', lambda: app)
    assert example.main() == 0
    assert capsys.readouterr().out == 'Example job counted active accounts: 1.\n'


def test_main_commits_inside_its_own_application_context(
    app: Flask, db: SQLAlchemy, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The example only reads, so its commit changes nothing to observe, but a copy that
    # writes depends on it. A commit after the with block would commit the fixture's
    # session here and raise under python -m, so the committing session must be main's.
    fixture_session = db.session()
    committed: list[object] = []
    monkeypatch.setattr(db.session, 'commit', lambda: committed.append(db.session()))
    example.main(app)
    assert len(committed) == 1
    assert committed[0] is not fixture_session
```

### scripts/systemd/job@.service — new

```ini
# Rendered by scripts/deploy.sh: __APP_NAME__ and __REPO_DIR__ come from the server's
# .env and clone location; installed as <APP_NAME>-job@.service. An instance runs the
# job it is named for: <APP_NAME>-job@example.service runs src_back/jobs/example.py in
# the running backend container, with the backend's environment. Its timer,
# <APP_NAME>-job@example.timer, starts it once enabled (ai/project.md, Scheduled Jobs).
# A failed or timed-out run starts <APP_NAME>-alert-job@example.service, which reports
# it through scripts/alert.sh.
[Unit]
Description=__APP_NAME__ scheduled job %i
After=docker.service
Requires=docker.service
OnFailure=__APP_NAME__-alert-job@%i.service

[Service]
Type=oneshot
WorkingDirectory=__REPO_DIR__
# Stopping `docker compose exec` leaves its process running in the container
# (moby/moby#9098), so timeout ends a run that outlasts an hour there, and the unit
# fails. python -u writes the job's output unbuffered, so the journal keeps what a
# stopped run printed. A oneshot unit has no start timeout by default, so
# TimeoutStartSec= ends a docker CLI that hangs, which would otherwise keep the timer
# from starting later runs.
ExecStart=/usr/bin/docker compose -f docker-compose.yml \
  -f docker/docker-compose.prod.yml --env-file .env \
  exec -T backend timeout 1h python -u -m src_back.jobs.%i
TimeoutStartSec=65min
```

### scripts/systemd/job@.timer — new

```ini
# Rendered by scripts/deploy.sh; installed as <APP_NAME>-job@.timer. Nothing runs until
# an instance is enabled: systemctl enable --now <APP_NAME>-job@example.timer runs
# <APP_NAME>-job@example.service daily. A job that needs another schedule gets a timer
# file of its own, job@<job>.timer, which systemd uses in place of this template
# (ai/project.md, Scheduled Jobs).
[Unit]
Description=Daily __APP_NAME__ scheduled job %i

[Timer]
# Half an hour after the 02:30 backup starts its dump, so a scheduled run's changes stay
# out of that morning's backup. A catch-up after a boot that missed both runs beside it.
OnCalendar=*-*-* 03:00:00 UTC
Persistent=true

[Install]
WantedBy=timers.target
```

### scripts/systemd/alert-job@.service — new

Modelled on `alert-restore-drill.service`.

```ini
# Rendered by scripts/deploy.sh; installed as <APP_NAME>-alert-job@.service and started
# by OnFailure= in job@.service, as <APP_NAME>-alert-job@<job>.service, when a run fails
# or times out.
[Unit]
Description=Report a failed __APP_NAME__ job %i

[Service]
Type=oneshot
WorkingDirectory=__REPO_DIR__
ExecStart=/bin/bash __REPO_DIR__/scripts/alert.sh \
  "__APP_NAME__: job %i FAILED" \
  "The job %i failed on %H. Inspect: journalctl -u __APP_NAME__-job@%i.service -n 50"
```

### scripts/deploy.sh — install the job templates in production

Lines 18-21, the end of the header comment:

```bash
# starts), install the nginx site (behind basic auth when STAGING_HTPASSWD is set), the
# certbot deploy hook, and the systemd units: certificate monitoring, the daily backup,
# and the weekly restore drill. The pre-migration backup, the certbot renewal hook, and
# the systemd units are production's alone.
```

become:

```bash
# starts), install the nginx site (behind basic auth when STAGING_HTPASSWD is set), the
# certbot deploy hook, and the systemd units: certificate monitoring, the daily backup,
# the weekly restore drill, and the scheduled-job templates, which run nothing until a
# job's timer is enabled. The pre-migration backup, the certbot renewal hook, and the
# systemd units are production's alone.
```

Line 247, `# staging branch's copy. Staging's data is not backed up.`, becomes:

```bash
# staging branch's copy. Staging's data is not backed up, and its jobs run by hand.
```

Lines 256-262, the comment and the echo before `render_systemd_unit()`:

```bash
  # Host-wide certificate monitoring, the daily backup, and the weekly restore drill.
  # The unit files carry __APP_NAME__ and __REPO_DIR__ placeholders so several apps on
  # one host each get their own units; the certbot drop-in is named per app because
  # systemd merges OnFailure= across drop-ins. The backup and drill units go in on
  # every deploy, bucket or not: backup.sh keeps local copies until install-backup.sh
  # adds the remote.
  echo "==> Installing certificate monitoring, backups, and the restore drill..."
```

become:

```bash
  # Host-wide certificate monitoring, the daily backup, the weekly restore drill, and
  # the scheduled-job templates. The unit files carry __APP_NAME__ and __REPO_DIR__
  # placeholders so several apps on one host each get their own units; the certbot
  # drop-in is named per app because systemd merges OnFailure= across drop-ins. The
  # backup and drill units go in on every deploy, bucket or not: backup.sh keeps local
  # copies until install-backup.sh adds the remote. The template enables no job's
  # timer; a project that keeps a job adds its timer to the enable call below
  # (ai/project.md, Scheduled Jobs).
  echo "==> Installing certificate monitoring, backups, the restore drill, and jobs..."
```

Lines 267-269, the unit list, gain the three templates:

```bash
  for unit in cert-check.service cert-check.timer alert-certbot.service \
    backup.service backup.timer restore-drill.service restore-drill.timer \
    alert-restore-drill.service job@.service job@.timer alert-job@.service; do
```

Lines 279-280, the non-production message, become:

```bash
  echo "==> $APP_ENVIRONMENT installs no renewal hook, backups, restore drill, jobs, or"
  echo "    certificate monitoring; production's cover this host's certificates."
```

The `systemctl enable --now` call at lines 276-277 does not change.

### scripts/tests/test-deploy.sh — check the job templates

In `assert_units_installed`, lines 213-219, the comment says "the eleven units" instead
of "the eight units", and the loop's last line gains the three templates:

```bash
    alert-restore-drill.service job@.service job@.timer alert-job@.service; do
```

After `assert_units_installed` (line 233), add a helper:

```bash
# unit_lines FILE -> FILE's lines with every backslash continuation joined to the line
# it continues and runs of spaces squeezed, as systemd reads a unit.
unit_lines() {
  awk '{ if (sub(/\\$/, "")) printf "%s", $0; else print }' "$1" | tr -s ' '
}
```

The redeploy comment, lines 235-239, says the run enables the timers "and no job's":

```bash
# A redeploy, with both data volumes present, starts the database for a pre-migration
# dump labelled with the commit read before the pull, hands the uploads volume to the
# backend's user, then rebuilds, waits for the backend, installs the nginx site and the
# renewal hook, and enables the three timers, and no job's, after one daemon-reload.
# Every call is listed, in order, so a step that moved or went missing shows.
```

The `expect_calls` list under it stays as it is: its exact `systemctl enable --now` line
is what proves the deploy enables no job's timer.

The comment at lines 263-265 becomes:

```bash
# What that run installed: every unit with its placeholders filled and mode 644, the
# backup, drill, and job units with the rendered paths, schedules, alerts, and
# timeouts, the nginx site in place of the stock one, and an executable renewal hook.
```

After line 279 (the `restore-drill\.log` assertion), add:

```bash
# The job template runs the job its instance names in the backend container, through
# Compose as deploy.sh calls it, under an hour's timeout inside the container, from the
# clone, as a oneshot whose start timeout bounds it, with an alert per job; its timer
# runs daily after the backup, and enabling it links it into timers.target.
unit_lines "$SYSTEMD_DIR/$APP-job@.service" > "$TEST_DIR/job-unit"
assert_line "$TEST_DIR/job-unit" \
  "ExecStart=/usr/bin/$COMPOSE exec -T backend timeout 1h python -u -m src_back.jobs.%i"
assert_line "$TEST_DIR/job-unit" "WorkingDirectory=$TEST_DIR/repo"
assert_line "$TEST_DIR/job-unit" 'Type=oneshot'
assert_line "$TEST_DIR/job-unit" "OnFailure=$APP-alert-job@%i.service"
assert_line "$TEST_DIR/job-unit" 'TimeoutStartSec=65min'
assert_line "$SYSTEMD_DIR/$APP-job@.timer" 'OnCalendar=*-*-* 03:00:00 UTC'
assert_line "$SYSTEMD_DIR/$APP-job@.timer" 'Persistent=true'
assert_line "$SYSTEMD_DIR/$APP-job@.timer" 'WantedBy=timers.target'
assert_contains "$APP: job %i FAILED" "$SYSTEMD_DIR/$APP-alert-job@.service"
assert_contains "journalctl -u $APP-job@%i\.service" \
  "$SYSTEMD_DIR/$APP-alert-job@.service"
```

`$COMPOSE` (lines 113-114) is the call the `expect_calls` checks hold `deploy.sh`'s
`compose()` to, so the unit cannot drift from the deploy's Compose flags. The staging and
`qa` case (lines 415-443) already fails on any installed systemd file.

### docker/job-loop.sh — new

```sh
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
```

There is no `set -e`: the loop handles every failure itself.

### scripts/tests/test-job-loop.sh — new

In the style of `test-entrypoint.sh`. 1700000000 is 2023-11-14 22:13:20 UTC, so 03:00
is 17200 seconds away, 23:00 2800, 22:14 40, 22:13 (passed) 86380, 00:00 6400, and
09:08 39280. 09:08 is the case that needs the leading zeros stripped: dash and bash read
`09` and `08` as bad octal, and without the strip the loop would run the job with no
wait.

```bash
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
```

### docker/backend.Dockerfile — copy the loop script

After line 24 (`COPY docker/entrypoint.sh docker/entrypoint.sh`), add:

```dockerfile
# A loop service runs a scheduled job on a host without systemd timers; nothing starts
# one by default (ai/project.md, Scheduled Jobs).
COPY docker/job-loop.sh docker/job-loop.sh
```

The development build's `chown -R ... docker` (line 36) covers the new file.

### scripts/tests/test-backend-image.sh — the image can run a job

Lines 8-10, from `# scripts/deploy.sh runs hands it over.` to the end of the header
comment, become:

```bash
# scripts/deploy.sh runs hands it over. It also checks that the image can run a
# scheduled job as scripts/systemd/job@.service does, under timeout, and holds
# docker/job-loop.sh. It needs a running Docker daemon; without one it exits 77, which
# scripts/tests/run-all.sh counts as a skip outside CI. It runs under macOS's bash 3.2
# and on Linux.
```

Lines 56-58, inside the `for tag` loop, become a loop over both scripts:

```bash
  # Both stacks start the backend with /bin/sh docker/entrypoint.sh, and a loop service
  # (ai/project.md, Scheduled Jobs) starts /bin/sh docker/job-loop.sh.
  for script in docker/entrypoint.sh docker/job-loop.sh; do
    run_in "$tag" sh -n "$script" ||
      fail "The app user cannot read $script in the $tag image."
  done
```

Line 60's path list continues onto a second line:

```bash
for path in src_back src_back/app.py migrations docker docker/entrypoint.sh \
  docker/job-loop.sh; do
```

After line 71 (the `UNOWNED` check), add:

```bash
# scripts/systemd/job@.service runs `timeout 1h python -u -m src_back.jobs.<job>` in
# the backend container, so the image needs timeout and must import the jobs.
run_in production timeout 60 python -c 'import src_back.jobs.example' ||
  fail 'The production image cannot import a job under timeout.'
```

### ai/project.md — the convention, the units, and why not Celery

In Project Structure, after line 10 (`api/`), add:

```markdown
    - `jobs/` - scheduled jobs, one module each, which `python -m src_back.jobs.<name>`
      runs once; `example.py` is the one to copy (Scheduled Jobs, below)
```

Line 48 gains `job loop,` between `entrypoint,` and `nginx config` (90 characters).
Lines 51-54, the `scripts/` entry, become:

```markdown
- `scripts/` - local tooling (ports, worktrees) and server provisioning, deployment
  (production and staging), TLS, and backup scripts; `scripts/systemd/` holds the units
  and timers a production deploy installs, and `scripts/tests/` the shell-script tests
  and `run-all.sh`, which checks every script's syntax and then runs them
```

Insert this section after line 160, before `## Worktrees`. Its Compose snippet sits in a
`text` fence, which Prettier leaves alone, so it keeps the Compose file's 2-space indent
and can be pasted as shown; `prettier --check .` would reformat a `yaml` fence in `ai/`
to Markdown's 4-space indent.

````markdown
## Scheduled Jobs

A scheduled job is a module in `src_back/jobs/` that `python -m src_back.jobs.<name>`
runs once. Its `main(app=None)` builds the app with `create_app()` unless a test passes
one, does its work inside one application context, commits, prints one line saying
what it did, and returns the exit status, which its `__main__` block raises as
`SystemExit`. An exception exits 1 with its traceback. Print rather than log: the app
installs no logging handler, so `logging` drops everything below a warning.
`src_back/jobs/example.py`, which counts the active accounts and changes nothing, is the
one to copy, and `src_back/tests/test_example_job.py` calls its `main()` with the `app`
fixture.

A job must be safe to run again: a timer catches up a run the server missed, anyone can
start one by hand, and a run can fail partway. Record what is done in the data, such as
a column stamped when a row is handled, and commit right after each outside effect, such
as an email, so a failure later in the run neither repeats the effect nor loses the
record of it. Keep times timezone-aware, as `datetime.now(UTC)` is.

Run a job once:

```bash
docker compose exec -T backend python -m src_back.jobs.example  # in the dev stack
.venv/bin/python -m src_back.jobs.example                       # locally, reading .env
docker compose -f docker-compose.yml -f docker/docker-compose.prod.yml --env-file .env \
  exec -T backend python -m src_back.jobs.example               # a server, staging too
systemctl start $APP_NAME-job@example.service                   # production's unit
```

A production deploy installs three templates from `scripts/systemd/`. An instance of
`$APP_NAME-job@.service` runs the job it is named for in the running backend container,
with the backend's environment:
`docker compose ... exec -T backend timeout 1h python -u -m src_back.jobs.<name>`.
`-u` keeps the output unbuffered, so the journal holds what a run printed even when
`timeout` stops it. `$APP_NAME-job@.timer` starts it daily at 03:00 UTC, half an hour
after the backup starts its dump, and catches up a run the server was off for.
`$APP_NAME-alert-job@.service` reports a run that exits non-zero or outlasts its hour
through `scripts/alert.sh`. The hour is enforced inside the container, because stopping
`docker compose exec` leaves its process running there (moby/moby#9098); the unit's
`TimeoutStartSec=` stops a docker CLI that hangs. A failed run is not retried; once the
cause is fixed, start the service by hand. A catch-up run after a boot can start before
the stack is up, fail, and alert once, as a catch-up backup can. A staging deploy
installs none of these units (`ai/staging.md`).

Nothing runs until a job's timer is enabled:

```bash
systemctl enable --now $APP_NAME-job@example.timer
systemctl list-timers "$APP_NAME-*"             # the next run of each timer
journalctl -u $APP_NAME-job@example.service     # what each run printed
systemctl disable --now $APP_NAME-job@example.timer
```

An enabled timer stays enabled across deploys, but a rebuilt server starts with none,
so a project that keeps a job adds its timer to the `systemctl enable --now` call in
`scripts/deploy.sh` and to the calls `scripts/tests/test-deploy.sh` expects. A job that
needs another schedule gets a timer of its own, `scripts/systemd/job@<name>.timer`: a
copy of `job@.timer` with its own `OnCalendar=`, added to the deploy's unit list and to
the units the test's `assert_units_installed` checks. systemd uses a unit file named for
an instance in place of the template.

### Why not Celery

Two derived apps adopted Celery with Redis for one daily job each, and neither job ran
reliably: neither worker imported the module that defines its task, and in one app beat
kept its schedule inside the container, so every deploy restarted the 24-hour countdown.
Nothing in either app enqueued work from a request. A timer needs no broker, worker, or
beat container, keeps its schedule across deploys, and reports a failure through
`scripts/alert.sh`, as the backups and the restore drill do. Celery and Redis come back
when requests enqueue work to run in the background, or when the work needs more than
one worker.

### Jobs without host access

A host that cannot run systemd timers, such as a container platform, runs a job in a
service of its own. `docker/job-loop.sh <job> <HH:MM>` sleeps until the next HH:MM UTC,
runs the job, retries a failed run every five minutes, and exits 1 after the third
failure in a row, so the restart policy and the platform's monitoring see it. It reads
the clock for every wait, so a restart keeps the schedule. The template starts no such
service. To add one, anchor the backend's `environment:` in
`docker/docker-compose.prod.yml` and add the service beside it:

```text
services:
  backend:
    environment: &backend-environment
      DATABASE_URL: ${DATABASE_URL}
      # ...the backend's other variables, unchanged
  job-example:
    build:
      context: .
      dockerfile: docker/backend.Dockerfile
    restart: unless-stopped
    entrypoint: ['/bin/sh', 'docker/job-loop.sh', 'example', '03:00']
    environment: *backend-environment
    depends_on:
      - backend
```

Run each job one way, through its timer or through a loop service, never both, or it
runs twice a day. A loop service has no `scripts/alert.sh`, so its exit is the only
signal; give it the uploads volume as well if the job touches stored files.
````

### ai/staging.md — staging runs no job on a timer

Lines 38-44, the paragraph that starts `A staging deploy leaves out what only production
needs`, become:

```markdown
A staging deploy leaves out what only production needs. It takes no pre-migration dump
and installs no backup timer or restore drill, because staging's data is a disposable
copy of production's, and `backup.sh` would push a staging dump through the host-wide
rclone remote, under whatever `BACKUP_PREFIX` staging's `.env` holds. It installs
neither the certbot renewal hook nor the certificate monitoring, because production's
hook and units cover every certificate on the host, and `certbot.timer` renews both. It
installs no scheduled-job units either, so no job runs on a timer against the copied
rows; try a job there by hand (`ai/project.md`, Scheduled Jobs), where mail is off. Of
the host's shared state, a staging deploy changes only its own nginx site.
```

### tools.md — the job units, `timeout`, and why Celery is out

Lines 25-27, **Bash and POSIX sh**, become:

```markdown
- **Bash and POSIX sh**: the scripts. `docker/entrypoint.sh`, `docker/job-loop.sh`, and
  the local helpers `up.sh`, `down.sh`, `docker-url.sh`, and `worktree-setup.sh` are
  POSIX sh; the server and deployment scripts and the Claude Code hook are Bash.
```

Lines 77-78, the start of **python-dotenv**, name the scheduled jobs; lines 79-81 stay:

```markdown
- **python-dotenv**: loads `.env` when `src_back/app.py` is imported, so the `flask`
  command, the seed, the scheduled jobs, and pytest read the same settings on the host;
```

Lines 260-262, **`python:3.12-slim`**, end with a sentence on `timeout`:

```markdown
- **`python:3.12-slim`**: the backend image base. It installs only `requirements.txt`,
  plus watchdog when the dev stack builds it, so the image carries no lint, type-check,
  or test tools. It runs the app as the unprivileged `app` user, uid 10001. Its
  coreutils supply the `timeout` that ends a scheduled job's run after an hour.
```

Lines 301-303, the Servers and operations introduction, end with "the monitoring,
backup, restore-drill, and scheduled-job units." Lines 318-324, **systemd**, become:

```markdown
- **systemd**: the units and timers under `scripts/systemd/`: the nightly backup at
  02:30 UTC, the weekly restore drill on Sundays at 04:00 UTC, the daily certificate
  expiry check at 05:00 UTC, the scheduled-job templates, which run a job from
  `src_back/jobs/` daily at 03:00 UTC once its timer is enabled, and the units that
  `OnFailure=` starts to report a failed certbot renewal, a failed or timed-out drill,
  and a failed or timed-out job. A production deploy installs them all, and
  `scripts/install-backup.sh` installs the backup and drill units too. The scripts
  render their `__APP_NAME__` and `__REPO_DIR__` placeholders so several apps can share
  a host. The job timers stand in for Celery and Redis, which the template leaves out
  until requests enqueue background work or the work needs more than one worker;
  `ai/project.md` says why.
```

Lines 346-349, **Webhooks**, become:

```markdown
- **Webhooks (ntfy.sh, Slack, or Discord)**: where `scripts/alert.sh` sends failed
  backups, failed restore drills, failed renewals, failed scheduled jobs, and expiring
  certificates. `ALERT_WEBHOOK_FORMAT` picks the payload shape, and the server's
  `python3` escapes the Slack and Discord JSON. With no URL set, alerts are only logged.
```

### README.md — the layout and the deployment summary

In Project layout, add this line after line 213 (`extensions.py`):

```text
│   ├── jobs/          # Scheduled jobs; example.py is the one to copy
```

and line 234 becomes:

```text
├── docker/            # Dockerfiles, entrypoint, job loop, nginx, production override
```

Lines 321-327 of the Deployment paragraph become:

```markdown
unprivileged user, rebuilds the containers, installs the nginx site, and enables
certificate monitoring, nightly backups kept on the server, and a weekly drill that
restores the newest one. It also installs the scheduled-job units, which run a job from
`src_back/jobs/` once its timer is enabled (`ai/project.md`). A staging deploy skips the
backup, the renewal hook, and the timers. Once the `SPACES_*` variables are filled in,
`bash scripts/install-backup.sh` adds off-site copies in a bucket. Failures alert
through `ALERT_WEBHOOK_URL`; `ai/backups.md` and `ai/tls.md` cover restores, alerts,
and renewals. `ai/staging.md` covers running staging beside production.
```

## Parallelism

- **Can be done in parallel**:
    - Group A, the backend: `src_back/jobs/__init__.py`, `src_back/jobs/example.py`,
      `src_back/tests/test_example_job.py`.
    - Group B, the units and the deploy: the three `scripts/systemd/` files,
      `scripts/deploy.sh`, `scripts/tests/test-deploy.sh`.
    - Group C, the loop and the image: `docker/job-loop.sh`,
      `scripts/tests/test-job-loop.sh`, `docker/backend.Dockerfile`,
      `scripts/tests/test-backend-image.sh`.
    - Group D, the documentation: `ai/project.md`, `ai/staging.md`, `tools.md`,
      `README.md`.
- **Must be sequential**: Group C's `test-backend-image.sh` imports
  `src_back.jobs.example`, so it runs only after Group A's module exists; Group C can
  write it before then. Within Group B, `test-deploy.sh` reads the unit files and the
  edited `deploy.sh`, so it runs last in its group.

## No other changes needed

- `scripts/alert.sh`: the new alert unit calls it with a subject and a body, as the
  other two alert units do.
- `scripts/install-backup.sh` and its test: it renders only the backup and drill units.
- The Compose files and `scripts/tests/test-compose-config.sh`: the systemd job runs in
  the existing backend container, and no loop service is added.
- `docker/entrypoint.sh`: `compose exec` bypasses it, so a job never runs the migrations
  or the seed.
- `src_back/mailer.py`, `.env.example`, `.env.staging.example`: no new variable.
- `pyproject.toml`: coverage already excludes `if __name__ == '__main__':` blocks, and
  `src_back/jobs/` falls under `--cov=src_back` and the existing lint paths.
- `.github/workflows/ci.yml`: `run-all.sh` finds `test-job-loop.sh` by its name and
  checks `docker/job-loop.sh` with `sh -n` by its shebang.
- `ai/conventions.md`, `ai/domain.md`, `ai/backups.md`, `ai/tls.md`.

## Verification

1. Targeted, while editing: `.venv/bin/python -m pytest
   src_back/tests/test_example_job.py --no-cov`, `bash scripts/tests/test-deploy.sh`,
   `bash scripts/tests/test-job-loop.sh`, and, with Docker running,
   `bash scripts/tests/test-backend-image.sh`. Run the loop and deploy tests as CI does
   too, where sh is dash and awk is mawk: `docker run --rm -v "$PWD":/repo:ro
   ubuntu:24.04 bash -c 'cd /repo && bash scripts/tests/test-job-loop.sh && bash
   scripts/tests/test-deploy.sh'`.
2. At the end, in parallel: `npm run test`, `npm run lint`, and `npm run lint:py`; then
   `npm run test:scripts`, `npm run lint:md`, and `npx prettier --check .`.
3. Against the dev stack (`npm run docker:up -- -d`, then `npm run docker:url`):
    - `docker compose exec -T backend python -m src_back.jobs.example` prints
      `Example job counted active accounts: <n>.` and exits 0, and
      `.venv/bin/python -m src_back.jobs.example` prints the same count.
    - `docker compose exec -T backend timeout 2 python -c 'import time; time.sleep(5)'`
      exits 124, so `timeout` ends a run inside the container.
    - `docker compose exec -T backend sh docker/job-loop.sh example 24:00` prints the
      usage and exits 1. Then `npm run docker:down`.
4. The documented loop service renders: copy `docker/docker-compose.prod.yml` to a
   scratch file, add the anchor and the `job-example` service from `ai/project.md`, and
   check that `docker compose -f docker-compose.yml -f <scratch> --env-file <test env>
   config --format json` gives `job-example` the loop entrypoint and the backend's
   `DATABASE_URL` and `FLASK_ENV`.
5. On a server, or the local stand-in from earlier rehearsals (systemd as PID 1 with an
   inner Docker), after a production deploy:
    - `ls /etc/systemd/system/<app>-*job*` lists the three templates, and
      `systemd-analyze verify <app>-job@example.service` reports nothing.
    - `systemctl enable --now <app>-job@example.timer`, then
      `systemctl list-timers '<app>-*'` shows it next at 03:00 UTC.
    - `systemctl start <app>-job@example.service`, then `journalctl -u
      <app>-job@example.service -n 5` shows the one line.
    - `systemctl start <app>-job@missing.service` fails, `<app>-alert-job@missing.service`
      runs, and `/var/log/<app>/alert.log` holds `<app>: job missing FAILED`.
    - A second deploy leaves the timer enabled (`systemctl is-enabled`).
