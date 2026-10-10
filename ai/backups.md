# Backups and Disaster Recovery

## Overview

Production keeps two kinds of durable state on the server: the Postgres database
(volume `<COMPOSE_PROJECT_NAME>_postgres_data`) and uploaded files (volume
`<COMPOSE_PROJECT_NAME>_uploads_data`, served at `/uploads/...`). Both are backed up
nightly to an S3-compatible bucket (DigitalOcean Spaces by default) by
`scripts/backup.sh`, run on a systemd timer. Every deploy also dumps the database
before running migrations.

Names below come from the server's `.env`: `$APP_NAME` names the systemd units and the
`/var/log/$APP_NAME` and `/var/backups/$APP_NAME` directories; `$COMPOSE_PROJECT_NAME`
(set to the same value by `provision.sh`) names the Docker volumes.

## Spaces layout

Backups live under the bucket named by `SPACES_BUCKET`, prefixed by `BACKUP_PREFIX`
(`prod`):

```text
prod/daily/db/db-<timestamp>.dump
prod/daily/uploads/uploads-<timestamp>.tar.gz
prod/weekly/db/... prod/weekly/uploads/...
prod/monthly/db/... prod/monthly/uploads/...
prod/premigration/db-<timestamp>.dump
```

Retention is count-based and pruned in-script: `RETAIN_DAILY` (14), `RETAIN_WEEKLY`
(8), `RETAIN_MONTHLY` (6). A copy is added to `weekly/` on Sundays and to `monthly/` on
the first of the month. The `premigration/` dumps are written by deploys (see below).

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
```

Secrets live only in `.env` (gitignored) and `/root/.config/rclone/rclone.conf` (mode
600). They are never committed.

## One-time setup

1. Create a bucket in the server's region and a dedicated access key pair.
2. Fill the `SPACES_*` values in `~/$APP_NAME/.env` on the server.
3. Run `bash ~/$APP_NAME/scripts/install-backup.sh`. It installs rclone, writes the
   rclone remote from `.env`, verifies the bucket is readable and writable, and
   enables `$APP_NAME-backup.timer`.
4. Rotate keys by updating `.env` and re-running `install-backup.sh`.

## Manual backup and logs

- Run now: `systemctl start $APP_NAME-backup.service`.
- Logs: `journalctl -u $APP_NAME-backup -e` or `/var/log/$APP_NAME/backup.log`.
- The daily timer runs at 02:30 UTC; check `systemctl list-timers "$APP_NAME-*"`.

## Pre-migration dumps

`scripts/deploy.sh` runs `scripts/backup.sh --pre-migration` whenever the
`<COMPOSE_PROJECT_NAME>_postgres_data` volume exists, starting the `db` container first
if the stack is stopped, before taking the stack down. Only a first deploy, with no data
volume yet, skips it. The dump is kept locally in
`/var/backups/$APP_NAME/pre-migration/` (newest three) and, once the rclone remote
exists, pushed to `premigration/` in the bucket. A failed pre-migration backup aborts
the deploy. To undo a bad migration, restore the newest local dump with the database
step of the disaster-recovery procedure below.

## Failure alerting

Every failure path in `backup.sh` calls `scripts/alert.sh`, which posts to
`ALERT_WEBHOOK_URL` from `.env` (`ALERT_WEBHOOK_FORMAT` is `text` for ntfy.sh, `slack`,
or `discord`) and logs to `/var/log/$APP_NAME/alert.log`. With no URL set the alert is
logged and delivered nowhere, so set one before relying on the backups. `backup.sh`
also refuses to archive an uploads volume that does not exist, since `docker run -v`
would otherwise create it empty and report a false success.

## Restore drill (follow-up)

Not ported. The source project ran a weekly timer that restored the latest bucket
backup into a throwaway database and verified it. This template has no second Postgres
to restore into, so adding a drill means starting a scratch `postgres:16` container,
running `pg_restore` of the newest `daily/db/` dump into it, checking a row count, and
removing the container. Until then, rehearse the manual procedure below on a scratch
server after the first real backup lands.

## Orphaned-volume cleanup

Only ever remove volumes confirmed empty and unused. NEVER touch
`<COMPOSE_PROJECT_NAME>_*`. Candidates are anonymous 64-hex volumes and volumes left
behind by an abandoned project name. For each candidate:

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

1. Fetch the chosen artifacts:

    ```bash
    cd ~/$APP_NAME
    rclone copyto spaces:<bucket>/prod/daily/db/<db-file> /tmp/<db-file>
    rclone copyto spaces:<bucket>/prod/daily/uploads/<up-file> /tmp/<up-file>
    ```

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
