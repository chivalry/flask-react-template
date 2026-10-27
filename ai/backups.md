# Backups and Disaster Recovery

## Overview

Production keeps two kinds of durable state on the server: the Postgres database
(volume `<COMPOSE_PROJECT_NAME>_postgres_data`) and uploaded files (volume
`<COMPOSE_PROJECT_NAME>_uploads_data`, served at `/uploads/...`). `scripts/backup.sh`,
run nightly on a systemd timer, dumps the database and archives the uploads. It keeps
the newest `RETAIN_LOCAL_DAILY` (7) of each on the server and, once a bucket is
configured, also pushes them to an S3-compatible bucket (DigitalOcean Spaces by
default). Every deploy also dumps the database before running migrations, and a
weekly restore drill proves that the newest backup restores.

Names below come from the server's `.env`: `$APP_NAME` names the systemd units and the
`/var/log/$APP_NAME` and `/var/backups/$APP_NAME` directories; `$COMPOSE_PROJECT_NAME`
(set to the same value by `provision.sh`) names the Docker volumes.

## Local copies

Every run keeps its files on the server first, under `/var/backups/$APP_NAME/`:

```text
daily/db-<timestamp>.dump
daily/uploads-<timestamp>.tar.gz
pre-migration/db-<timestamp>-<commit>.dump
```

`daily/` keeps the newest `RETAIN_LOCAL_DAILY` of each kind, and `pre-migration/` the
newest three. Until the rclone remote exists, a daily run keeps only these copies: it
logs `WARN: Spaces remote not configured; kept LOCAL daily backup only` and succeeds.
Local copies die with the server, so they stand in for a bucket only until one exists.

Local copies cost disk: at the default of 7, the archives of a 3 GB uploads volume take
about 21 GB, so lower `RETAIN_LOCAL_DAILY` on a small disk. A run refuses to start with
under about 2 GB free on the disk that holds `/var/backups/$APP_NAME`.

## Spaces layout

Backups live under the bucket named by `SPACES_BUCKET`, prefixed by `BACKUP_PREFIX`
(`prod`):

```text
prod/daily/db/db-<timestamp>.dump
prod/daily/uploads/uploads-<timestamp>.tar.gz
prod/weekly/db/... prod/weekly/uploads/...
prod/monthly/db/... prod/monthly/uploads/...
prod/premigration/db-<timestamp>-<commit>.dump
```

Retention in the bucket is count-based and pruned in-script: `RETAIN_DAILY` (14),
`RETAIN_WEEKLY` (8), `RETAIN_MONTHLY` (6). A copy is added to `weekly/` on Sundays and
to `monthly/` on the first of the month. The `premigration/` dumps are written by
deploys (see below).

## Environment variables (server `.env` only)

```text
APP_NAME=<app name>
COMPOSE_PROJECT_NAME=<app name>
SPACES_ENDPOINT=https://<region>.digitaloceanspaces.com
SPACES_REGION=<region>
SPACES_BUCKET=<bucket>
SPACES_ACCESS_KEY_ID=<key>
SPACES_SECRET_ACCESS_KEY=<secret>
BACKUP_PREFIX=prod
RETAIN_DAILY=14
RETAIN_WEEKLY=8
RETAIN_MONTHLY=6
RETAIN_LOCAL_DAILY=7
BACKUP_COMPOSE_FILE=
```

`BACKUP_COMPOSE_FILE` names the Compose override `backup.sh` loads over
`docker-compose.yml`; blank means `docker/docker-compose.prod.yml`, and
`backup.sh --compose-file <path>` wins over it. Every `RETAIN_*` count must be a whole
number above 0, or `backup.sh` fails and alerts before it dumps anything.

Secrets live only in `.env` (gitignored) and `/root/.config/rclone/rclone.conf` (mode
600). They are never committed.

## Setup

1. Local backups need no setup: `scripts/deploy.sh` installs and enables
   `$APP_NAME-backup.timer` and `$APP_NAME-restore-drill.timer` on every deploy.
2. For off-site copies, create a bucket in the server's region and a dedicated access
   key pair, then fill the `SPACES_*` values in `~/$APP_NAME/.env` on the server.
3. Run `bash ~/$APP_NAME/scripts/install-backup.sh`. It installs rclone, writes the
   rclone remote from `.env`, verifies the bucket is readable and writable, and renders
   and enables the same two timers. From the next run, backups also go to the bucket,
   and the drill restores from it. If that check fails, the remote is already written,
   so every push to the bucket fails and alerts, and deploys stop at their
   pre-migration backup, until a re-run passes.
4. Rotate keys by updating `.env` and re-running `install-backup.sh`.

## Manual runs and logs

- Backup: run it now with `systemctl start $APP_NAME-backup.service`. It logs to
  `/var/log/$APP_NAME/backup.log`, and the timer runs it daily at 02:30 UTC.
- Restore drill: run it now with `systemctl start $APP_NAME-restore-drill.service`. It
  logs to `/var/log/$APP_NAME/restore-drill.log`, and the timer runs it on Sundays at
  04:00 UTC.
- Check `systemctl list-timers "$APP_NAME-*"` for the next runs, and
  `journalctl -u $APP_NAME-backup -e` or `journalctl -u $APP_NAME-restore-drill -e` for
  what systemd saw, such as a drill stopped by its one-hour timeout.

## Pre-migration dumps

`scripts/deploy.sh` runs `scripts/backup.sh --pre-migration --label <commit>` whenever
the `<COMPOSE_PROJECT_NAME>_postgres_data` volume exists, starting the `db` container
first if the stack is stopped, before taking the stack down. Only a first deploy, with
no data volume yet, skips it. `<commit>` is the full commit checked out before the
deploy's `git pull`, which is the release whose schema the dump holds, unless an
earlier deploy failed after pulling. The dump is named `db-<timestamp>-<commit>.dump`,
so the commit in its name identifies the code that matches its schema. It is kept
locally in `/var/backups/$APP_NAME/pre-migration/` (newest three) and, once the rclone
remote exists, pushed to `premigration/` in the bucket. A failed pre-migration backup
aborts the deploy. To undo a bad migration, restore the newest local dump with the
database step of the disaster-recovery procedure below.

## Failure alerting

Every failure path in `backup.sh` calls `scripts/alert.sh`, which posts to
`ALERT_WEBHOOK_URL` from `.env` (`ALERT_WEBHOOK_FORMAT` is `text` for ntfy.sh, `slack`,
or `discord`) and logs to `/var/log/$APP_NAME/alert.log`. With no URL set the alert is
logged and delivered nowhere, so set one before relying on the backups. `backup.sh`
also refuses to archive an uploads volume that does not exist, since `docker run -v`
would otherwise create it empty and report a false success.

The restore drill never calls `alert.sh` itself. `OnFailure=` in
`restore-drill.service` starts `$APP_NAME-alert-restore-drill.service`, which calls it
whenever a drill exits non-zero or passes its one-hour timeout, so each failure alerts
once. The alert names `/var/log/$APP_NAME/restore-drill.log`, which holds the reason. A
drill run with plain `bash` logs the same but alerts nobody.

## Restore drill

`$APP_NAME-restore-drill.timer` runs `scripts/restore-drill.sh` on Sundays at 04:00 UTC,
and at the next boot if the server was off then. Each run does this:

1. It takes the newest database dump and uploads archive from the bucket once the
   remote exists, otherwise from `daily/` on the server.
2. It fails on a dump more than 48 hours old: backups run daily, so an older dump means
   they stopped reaching where the drill looks.
3. It starts the scratch `postgres:16` container `$APP_NAME-restore-drill`, with no
   network and production's `POSTGRES_USER` and `POSTGRES_DB`, and restores the dump
   with `pg_restore --no-owner --no-privileges --exit-on-error`.
4. It logs every table's row count and fails unless `users` has rows and
   `alembic_version` exactly one.
5. It lists the archive end to end without extracting it, logs its file count, and
   checks that it holds one stored path from each `UPLOAD_COLUMNS` column the restored
   schema has, skipping a column with no stored path.
6. It removes the container, its volume, and its files however it exits, and logs
   `SUCCESS` or the `FAILURE` reason.

Things to know:

- A server with no accounts (no `ADMIN_EMAIL` at its first deploy) fails until one
  exists.
- A drill before the first nightly backup fails, with `no daily backups yet` in the log
  when no bucket is configured.
- The drill is deliberately not ordered after the backup, so a hung backup cannot keep
  it from starting. The cost: after two or more days of downtime spanning a Sunday
  04:00, the catch-up drill can start before the catch-up backup finishes and alert
  once about an old dump.
- `UPLOAD_COLUMNS` at the top of the script is empty because the template stores no
  upload paths. Add `table.column` in the same change as the migration that creates
  such a column; a dump from before the migration lacks the column, so the drill skips
  it.
- `DRILL_IMAGE` must match the `db` service's image, since `pg_restore` refuses dumps
  from a newer server. `scripts/tests/test-restore-drill.sh` enforces it.

## Orphaned-volume cleanup

Only ever remove volumes confirmed empty and unused. NEVER touch
`<COMPOSE_PROJECT_NAME>_*`. Candidates are anonymous 64-hex volumes and volumes left
behind by an abandoned project name. The restore drill removes its own anonymous data
volume (`docker rm -f -v`), so a finished drill leaves none behind. A
`$APP_NAME-restore-drill` container left by a drill killed outright is removed, with
its volume, by the next drill. For each candidate:

1. Confirm no container uses it — `docker ps -a --filter volume=<vol>` is empty.
2. Confirm it holds no cluster:

    ```bash
    docker run --rm -v <vol>:/v:ro alpine \
      sh -c 'ls -A /v; test ! -e /v/PG_VERSION && echo NO_PGDATA; du -sh /v'
    ```

    Expect an empty listing, `NO_PGDATA`, and ~0 size. If `PG_VERSION` is present,
    STOP — it holds data.

3. Remove — `docker volume rm <vol>` (refuses in-use volumes as a final safety net).

## Disaster-recovery restore (manual)

This is deliberately not scripted. To restore production from a backup, on the server
as root:

1. Put the chosen artifacts in `/tmp`, where steps 3 and 4 read them. From the bucket:

    ```bash
    cd ~/$APP_NAME
    rclone copyto spaces:<bucket>/prod/daily/db/<db-file> /tmp/<db-file>
    rclone copyto spaces:<bucket>/prod/daily/uploads/<up-file> /tmp/<up-file>
    ```

    Or, if the server still has them, copy them there from
    `/var/backups/$APP_NAME/daily/`.

2. Stop the backend so nothing writes during the restore:

    ```bash
    docker compose -f docker-compose.yml -f docker/docker-compose.prod.yml \
      --env-file .env stop backend
    ```

3. Restore the database (`POSTGRES_USER` and `POSTGRES_DB` are in `.env`):

    ```bash
    docker compose -f docker-compose.yml -f docker/docker-compose.prod.yml \
      --env-file .env exec -T db pg_restore -U <POSTGRES_USER> -d <POSTGRES_DB> \
      --clean --if-exists --no-owner < /tmp/<db-file>
    ```

4. Restore uploads into the `<COMPOSE_PROJECT_NAME>_uploads_data` volume:

    ```bash
    docker run --rm -v <COMPOSE_PROJECT_NAME>_uploads_data:/to -v /tmp:/from alpine \
      sh -c 'rm -rf /to/* && tar xzf /from/<up-file> -C /to'
    ```

5. Start the backend again:

    ```bash
    docker compose -f docker-compose.yml -f docker/docker-compose.prod.yml \
      --env-file .env start backend
    ```
