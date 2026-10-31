#!/usr/bin/env bash
# Deploy or redeploy the app on the server. Run as root from inside the clone; normally
# invoked from a laptop by scripts/remote-deploy.sh (npm run deploy or npm run
# deploy:staging), which runs
#   bash ~/<APP_NAME>/scripts/deploy.sh --environment <name>
# --environment defaults to production. It must match APP_ENVIRONMENT in the clone's
# .env, where blank means production, and the clone must be on DEPLOY_BRANCH, where
# blank means main. So a staging clone holding production's .env, or a production clone
# switched to staging, is refused before anything changes.
# Assumes provision.sh has run, .env exists in the clone, and certbot-setup.sh has
# issued the certificate the nginx site references.
#
# Steps: pre-flight checks (Compose project + data volumes, certificate present, branch),
# git pull, pre-migration database backup named for the commit that was running
# (starting the database first if the stack is stopped), hand the uploads volume to the
# backend's unprivileged user, rebuild and restart the stack, wait for the backend to
# report healthy (its entrypoint runs the migrations and the seed before gunicorn
# starts), install the nginx site (behind basic auth when STAGING_HTPASSWD is set), the
# certbot deploy hook, and the systemd units: certificate monitoring, the daily backup,
# the weekly restore drill, and the scheduled-job templates, which run nothing until a
# job's timer is enabled. The pre-migration backup, the certbot renewal hook, and the
# systemd units are production's alone.
set -euo pipefail

usage() {
  echo "usage: bash scripts/deploy.sh [--environment <name>]"
  exit 1
}
REQUESTED_ENVIRONMENT=production
while [ $# -gt 0 ]; do
  case "$1" in
    --environment)
      [ $# -ge 2 ] && [ -n "$2" ] || usage
      REQUESTED_ENVIRONMENT=$2
      shift 2
      ;;
    --environment=?*) REQUESTED_ENVIRONMENT=${1#--environment=}; shift ;;
    *) usage ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
cd "$REPO_DIR"

if [ ! -f .env ]; then
  echo "ERROR: .env not found in $REPO_DIR."
  echo "       Run 'bash scripts/provision.sh <domain>' first."
  exit 1
fi

get() { grep -E "^$1=" .env | tail -1 | cut -d= -f2- || true; }

APP_NAME="$(get APP_NAME)"
DOMAIN="$(get DOMAIN)"
if [ -z "$APP_NAME" ]; then
  echo "ERROR: APP_NAME is empty in $REPO_DIR/.env. Refusing to deploy."
  exit 1
fi
if [ -z "$DOMAIN" ]; then
  echo "ERROR: DOMAIN is empty in $REPO_DIR/.env. Refusing to deploy."
  exit 1
fi
if [ -z "$(get PUBLIC_BASE_URL)" ]; then
  echo "ERROR: PUBLIC_BASE_URL is empty in $REPO_DIR/.env. Refusing to deploy."
  echo "       Add PUBLIC_BASE_URL=https://$DOMAIN; ai/auth.md explains it."
  exit 1
fi
APP_ENVIRONMENT="$(get APP_ENVIRONMENT)"
APP_ENVIRONMENT="${APP_ENVIRONMENT:-production}"
if [ "$APP_ENVIRONMENT" != "$REQUESTED_ENVIRONMENT" ]; then
  echo "ERROR: asked to deploy $REQUESTED_ENVIRONMENT, but $REPO_DIR/.env deploys"
  echo "       $APP_ENVIRONMENT; pass --environment $APP_ENVIRONMENT for that."
  exit 1
fi
DEPLOY_BRANCH="$(get DEPLOY_BRANCH)"
DEPLOY_BRANCH="${DEPLOY_BRANCH:-main}"
STAGING_HTPASSWD="$(get STAGING_HTPASSWD)"
if [ -n "$STAGING_HTPASSWD" ] && [ ! -f "$STAGING_HTPASSWD" ]; then
  echo "ERROR: STAGING_HTPASSWD names $STAGING_HTPASSWD, which does not exist."
  echo "       Create it (ai/staging.md) or clear the setting. Refusing to deploy."
  exit 1
fi
BACKEND_PORT="$(get BACKEND_PORT)"; BACKEND_PORT="${BACKEND_PORT:-5000}"
FRONTEND_HOST_PORT="$(get FRONTEND_HOST_PORT)"
FRONTEND_HOST_PORT="${FRONTEND_HOST_PORT:-8080}"
LOG_DIR="/var/log/$APP_NAME"
NGINX_SITE="$APP_NAME"
CERT_DIR="/etc/letsencrypt/live/$DOMAIN"
# The uid the backend image runs as (docker/backend.Dockerfile's useradd --uid);
# scripts/tests/test-deploy.sh checks that the two agree.
BACKEND_UID=10001

compose() {
  docker compose -f docker-compose.yml -f docker/docker-compose.prod.yml \
    --env-file .env "$@"
}

# wait_for <label> <service> <probe...>: run the probe every 2 s for up to 2 minutes.
# The deadline keeps a crashed or misconfigured service from hanging the deploy and
# the SSH session that invoked it; on timeout the service's recent log is printed.
wait_for() {
  local label="$1" service="$2"
  shift 2
  local attempt
  for attempt in $(seq 1 60); do
    if "$@" >/dev/null 2>&1; then
      return 0
    fi
    echo "   waiting for $label ($attempt/60)..."
    sleep 2
  done
  echo "ERROR: $label did not become ready within 2 minutes. Recent log:"
  compose logs --tail 50 "$service" || true
  exit 1
}
wait_for_db() { wait_for "database" db compose exec -T db pg_isready; }
wait_for_backend() {
  wait_for "backend" backend curl -fsS "http://127.0.0.1:$BACKEND_PORT/api/health"
}

# Pre-flight: assert the resolved Compose project + its data volumes, so a
# misconfigured .env can never deploy into (and orphan) the wrong volume set.
PROJECT="$(get COMPOSE_PROJECT_NAME)"
if [ -z "$PROJECT" ]; then
  echo "ERROR: COMPOSE_PROJECT_NAME is not set in $REPO_DIR/.env."
  echo "       It pins the data volumes (<name>_postgres_data, <name>_uploads_data);"
  echo "       without it Compose would pick a name itself. Refusing to deploy."
  exit 1
fi
PG_VOLUME="${PROJECT}_postgres_data"
UPLOADS_VOLUME="${PROJECT}_uploads_data"
if docker volume inspect "$PG_VOLUME" >/dev/null 2>&1 \
  || docker volume inspect "$UPLOADS_VOLUME" >/dev/null 2>&1; then
  for v in "$PG_VOLUME" "$UPLOADS_VOLUME"; do
    if ! docker volume inspect "$v" >/dev/null 2>&1; then
      echo "ERROR: expected volume '$v' missing — aborting to avoid data loss."
      exit 1
    fi
  done
  echo "==> Pre-flight OK: project '$PROJECT' (postgres_data + uploads_data present)."
  FIRST_DEPLOY=0
else
  echo "==> Pre-flight: no data volumes for '$PROJECT' yet — treating as first deploy."
  FIRST_DEPLOY=1
fi

# The nginx site below references the certificate; check now rather than after the
# stack has already been taken down and rebuilt.
if [ ! -f "$CERT_DIR/fullchain.pem" ]; then
  echo "ERROR: no certificate at $CERT_DIR. Run 'bash scripts/certbot-setup.sh' first."
  exit 1
fi

# The clone deploys only the branch its .env names, so the production clone never
# deploys staging's commits, or the reverse.
CURRENT_BRANCH="$(git symbolic-ref --quiet --short HEAD)" ||
  CURRENT_BRANCH='a detached HEAD'
if [ "$CURRENT_BRANCH" != "$DEPLOY_BRANCH" ]; then
  echo "ERROR: $REPO_DIR is on $CURRENT_BRANCH, but its .env deploys $DEPLOY_BRANCH."
  echo "       Run 'git switch $DEPLOY_BRANCH' there first. Refusing to deploy."
  exit 1
fi

echo "==> Deploying '$APP_NAME' ($APP_ENVIRONMENT) for https://$DOMAIN"

# The commit checked out before the pull is the release whose schema the database
# holds, unless an earlier deploy failed after pulling; the pre-migration dump is
# named for it.
RUNNING_COMMIT="$(git rev-parse HEAD)"

echo "==> Pulling latest code..."
git pull

# Pre-migration DB backup: dump the CURRENT (old) database before down/upgrade so a
# bad migration is instantly reversible. Keyed on the data volume rather than on a
# running container, so a stopped stack still gets its dump; only a first deploy, with
# no data volume yet, has nothing to back up. Only production takes one: staging's data
# is a disposable copy, and backup.sh would push the dump through the host-wide rclone
# remote, under whatever BACKUP_PREFIX staging's .env holds.
if [ "$APP_ENVIRONMENT" != production ]; then
  echo "==> $APP_ENVIRONMENT deploys take no pre-migration backup."
elif [ "$FIRST_DEPLOY" = 0 ]; then
  echo "==> Ensuring the database is running for the pre-migration backup..."
  compose up -d db
  wait_for_db
  echo "==> Pre-migration DB backup..."
  if ! bash scripts/backup.sh --pre-migration --label "$RUNNING_COMMIT"; then
    echo "ERROR: pre-migration backup failed — see $LOG_DIR/backup.log"
    exit 1
  fi
else
  echo "==> First deploy: no database to back up yet."
fi

# Docker gives a new, empty uploads volume to the backend's user, but never re-owns
# one that already holds files: files written while the backend ran as root, or
# restored from an older archive. Saving an upload would then fail while
# /api/health stays healthy. This runs before the stack goes down, so a failure
# leaves the old stack serving.
if [ "$FIRST_DEPLOY" = 0 ]; then
  echo "==> Handing the uploads volume to the backend's user..."
  if ! docker run --rm -v "$UPLOADS_VOLUME:/uploads" alpine \
    chown -R "$BACKEND_UID:$BACKEND_UID" /uploads; then
    echo "ERROR: could not hand $UPLOADS_VOLUME to uid $BACKEND_UID."
    exit 1
  fi
fi

echo "==> Stopping existing containers..."
compose down

echo "==> Building and starting containers..."
# A service dropped from the Compose files would otherwise leave its container running.
compose up -d --build --remove-orphans

# docker/entrypoint.sh owns the migrations and the seed and starts gunicorn only after
# both succeed, so a healthy backend means the schema is current. Running `db upgrade`
# here as well would race the entrypoint's run on the same migration.
echo "==> Waiting for the backend to report healthy..."
wait_for_backend

echo "==> Installing nginx site config ($NGINX_SITE)..."
rm -f /etc/nginx/sites-enabled/default
# STAGING_HTPASSWD puts the whole site behind a password; both directives go on the
# template's basic-auth line, which is left blank otherwise.
BASIC_AUTH=''
if [ -n "$STAGING_HTPASSWD" ]; then
  BASIC_AUTH="auth_basic \"$APP_NAME\"; auth_basic_user_file $STAGING_HTPASSWD;"
fi
sed -e "s|__APP_NAME__|$APP_NAME|g" -e "s|__DOMAIN__|$DOMAIN|g" \
  -e "s|__BACKEND_PORT__|$BACKEND_PORT|g" \
  -e "s|__FRONTEND_HOST_PORT__|$FRONTEND_HOST_PORT|g" \
  -e "s|__BASIC_AUTH__|$BASIC_AUTH|g" \
  scripts/nginx-ssl.conf.template > "/etc/nginx/sites-available/$NGINX_SITE"
ln -sf "/etc/nginx/sites-available/$NGINX_SITE" "/etc/nginx/sites-enabled/$NGINX_SITE"
systemctl enable nginx
# `nginx -t && systemctl reload nginx` would let a broken config slip past set -e (a
# failing left-hand side of && does not abort), so the test stands on its own line.
# reload-or-restart also covers nginx being stopped, as certbot-setup.sh leaves it.
nginx -t
systemctl reload-or-restart nginx

# The renewal hook, the certificate monitoring, and the backups are production's alone.
# Production's cert-check covers every certificate on the host, and its certbot drop-in
# fires on any failed renewal. Its renewal hook, one host-wide file, reloads nginx after
# any renewal, staging's included, so a staging deploy must not replace it with the
# staging branch's copy. Staging's data is not backed up, and its jobs run by hand.
if [ "$APP_ENVIRONMENT" = production ]; then
  echo "==> Installing certbot renewal hook..."
  # certbot creates renewal-hooks/ on its first run, not at package install, so on a
  # host where deploy.sh runs before any certificate exists the directory is absent.
  mkdir -p /etc/letsencrypt/renewal-hooks/deploy
  install -m 0755 scripts/letsencrypt-deploy-hook.sh \
    /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh

  # Host-wide certificate monitoring, the daily backup, the weekly restore drill, and
  # the scheduled-job templates. The unit files carry __APP_NAME__ and __REPO_DIR__
  # placeholders so several apps on one host each get their own units; the certbot
  # drop-in is named per app because systemd merges OnFailure= across drop-ins. The
  # backup and drill units go in on every deploy, bucket or not: backup.sh keeps local
  # copies until install-backup.sh adds the remote. The template enables no job's
  # timer; a project that keeps a job adds its timer to the enable call below
  # (ai/project.md, Scheduled Jobs).
  echo "==> Installing certificate monitoring, backups, the restore drill, and jobs..."
  render_systemd_unit() {  # <template> <destination>
    sed -e "s|__APP_NAME__|$APP_NAME|g" -e "s|__REPO_DIR__|$REPO_DIR|g" "$1" > "$2"
    chmod 644 "$2"
  }
  for unit in cert-check.service cert-check.timer alert-certbot.service \
    backup.service backup.timer restore-drill.service restore-drill.timer \
    alert-restore-drill.service job@.service job@.timer alert-job@.service; do
    render_systemd_unit "scripts/systemd/$unit" "/etc/systemd/system/$APP_NAME-$unit"
  done
  mkdir -p /etc/systemd/system/certbot.service.d
  render_systemd_unit scripts/systemd/certbot-onfailure.conf \
    "/etc/systemd/system/certbot.service.d/$APP_NAME-onfailure.conf"
  systemctl daemon-reload
  systemctl enable --now "$APP_NAME-cert-check.timer" "$APP_NAME-backup.timer" \
    "$APP_NAME-restore-drill.timer"
else
  echo "==> $APP_ENVIRONMENT installs no renewal hook, backups, restore drill, jobs, or"
  echo "    certificate monitoring; production's cover this host's certificates."
fi

echo ""
echo "==> Deployment complete ($APP_ENVIRONMENT): https://$DOMAIN"
