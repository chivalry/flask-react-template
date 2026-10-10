#!/usr/bin/env bash
# Deploy or redeploy the app on the server. Run as root from inside the clone; normally
# invoked from a laptop by scripts/remote-deploy.sh (npm run deploy), which runs
#   bash ~/<APP_NAME>/scripts/deploy.sh
# Assumes provision.sh has run, .env exists in the clone, and certbot-setup.sh has
# issued the certificate the nginx site references.
#
# Steps: pre-flight checks (Compose project + data volumes, certificate present),
# git pull, pre-migration database backup (starting the database first if the stack is
# stopped), rebuild and restart the stack, wait for the backend to report healthy (its
# entrypoint runs the migrations and the seed before gunicorn starts), install the
# nginx site, the certbot deploy hook, and the certificate monitoring units.
set -euo pipefail

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
BACKEND_PORT="$(get BACKEND_PORT)"; BACKEND_PORT="${BACKEND_PORT:-5000}"
FRONTEND_HOST_PORT="$(get FRONTEND_HOST_PORT)"
FRONTEND_HOST_PORT="${FRONTEND_HOST_PORT:-8080}"
LOG_DIR="/var/log/$APP_NAME"
NGINX_SITE="$APP_NAME"
CERT_DIR="/etc/letsencrypt/live/$DOMAIN"

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

echo "==> Deploying '$APP_NAME' ($REPO_DIR) for https://$DOMAIN"

echo "==> Pulling latest code..."
git pull

# Pre-migration DB backup: dump the CURRENT (old) database before down/upgrade so a
# bad migration is instantly reversible. Keyed on the data volume rather than on a
# running container, so a stopped stack still gets its dump; only a first deploy, with
# no data volume yet, has nothing to back up.
if [ "$FIRST_DEPLOY" = 0 ]; then
  echo "==> Ensuring the database is running for the pre-migration backup..."
  compose up -d db
  wait_for_db
  echo "==> Pre-migration DB backup..."
  if ! bash scripts/backup.sh --pre-migration; then
    echo "ERROR: pre-migration backup failed — see $LOG_DIR/backup.log"
    exit 1
  fi
else
  echo "==> First deploy: no database to back up yet."
fi

echo "==> Stopping existing containers..."
compose down

echo "==> Building and starting containers..."
compose up -d --build

# docker/entrypoint.sh owns the migrations and the seed and starts gunicorn only after
# both succeed, so a healthy backend means the schema is current. Running `db upgrade`
# here as well would race the entrypoint's run on the same migration.
echo "==> Waiting for the backend to report healthy..."
wait_for_backend

echo "==> Installing nginx site config ($NGINX_SITE)..."
rm -f /etc/nginx/sites-enabled/default
sed -e "s|__DOMAIN__|$DOMAIN|g" \
  -e "s|__BACKEND_PORT__|$BACKEND_PORT|g" \
  -e "s|__FRONTEND_HOST_PORT__|$FRONTEND_HOST_PORT|g" \
  scripts/nginx-ssl.conf.template > "/etc/nginx/sites-available/$NGINX_SITE"
ln -sf "/etc/nginx/sites-available/$NGINX_SITE" "/etc/nginx/sites-enabled/$NGINX_SITE"
systemctl enable nginx
# `nginx -t && systemctl reload nginx` would let a broken config slip past set -e (a
# failing left-hand side of && does not abort), so the test stands on its own line.
# reload-or-restart also covers nginx being stopped, as certbot-setup.sh leaves it.
nginx -t
systemctl reload-or-restart nginx

echo "==> Installing certbot renewal hook..."
# certbot creates renewal-hooks/ on its first run, not at package install, so on a
# host where deploy.sh runs before any certificate exists the directory is absent.
mkdir -p /etc/letsencrypt/renewal-hooks/deploy
install -m 0755 scripts/letsencrypt-deploy-hook.sh \
  /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh

# Host-wide certificate monitoring. The unit files carry __APP_NAME__ and __REPO_DIR__
# placeholders so several apps on one host each get their own units; the certbot
# drop-in is named per app because systemd merges OnFailure= across drop-ins.
echo "==> Installing certificate monitoring..."
render_systemd_unit() {  # <template> <destination>
  sed -e "s|__APP_NAME__|$APP_NAME|g" -e "s|__REPO_DIR__|$REPO_DIR|g" "$1" > "$2"
  chmod 644 "$2"
}
render_systemd_unit scripts/systemd/cert-check.service \
  "/etc/systemd/system/$APP_NAME-cert-check.service"
render_systemd_unit scripts/systemd/cert-check.timer \
  "/etc/systemd/system/$APP_NAME-cert-check.timer"
render_systemd_unit scripts/systemd/alert-certbot.service \
  "/etc/systemd/system/$APP_NAME-alert-certbot.service"
mkdir -p /etc/systemd/system/certbot.service.d
render_systemd_unit scripts/systemd/certbot-onfailure.conf \
  "/etc/systemd/system/certbot.service.d/$APP_NAME-onfailure.conf"
systemctl daemon-reload
systemctl enable --now "$APP_NAME-cert-check.timer"

echo ""
echo "==> Deployment complete: https://$DOMAIN"
