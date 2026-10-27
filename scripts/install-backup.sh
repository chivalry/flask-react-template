#!/usr/bin/env bash
# One-time (idempotent) installer for the off-site half of the backups. Installs
# rclone, writes the rclone 'spaces:' remote from the server's .env, verifies the
# bucket is readable and writable, then renders and enables the backup and
# restore-drill units. deploy.sh renders the same units on every deploy, so local
# backups and the drill run without a bucket; this adds the bucket. Run as root from
# inside the clone, after filling SPACES_* in .env. Re-run after rotating Spaces keys
# or editing the unit files.
# Usage: bash scripts/install-backup.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
cd "$REPO_DIR"

get() { grep -E "^$1=" .env | tail -1 | cut -d= -f2- || true; }

APP_NAME="$(get APP_NAME)"
if [ -z "$APP_NAME" ]; then
  echo "ERROR: APP_NAME is empty in $REPO_DIR/.env." >&2
  exit 1
fi
BUCKET="$(get SPACES_BUCKET)"
if [ -z "$BUCKET" ]; then
  echo "ERROR: SPACES_BUCKET is empty in $REPO_DIR/.env; nothing to back up to." >&2
  exit 1
fi

if ! command -v rclone >/dev/null 2>&1; then
  echo "==> Installing rclone..."
  apt-get update -qq && apt-get install -y rclone
fi

# The units run as root, so the remote lives in root's rclone config.
mkdir -p /root/.config/rclone "/var/log/$APP_NAME" "/var/backups/$APP_NAME"
# What backup.sh keeps here holds the database and the uploads; backup.sh and
# restore-drill.sh close the directory the same way before they write to it.
chmod 700 "/var/backups/$APP_NAME"

echo "==> Writing rclone Spaces remote..."
umask 077
cat > /root/.config/rclone/rclone.conf <<CONF
[spaces]
type = s3
provider = DigitalOcean
env_auth = false
access_key_id = $(get SPACES_ACCESS_KEY_ID)
secret_access_key = $(get SPACES_SECRET_ACCESS_KEY)
region = $(get SPACES_REGION)
endpoint = $(get SPACES_ENDPOINT)
acl = private
CONF
chmod 600 /root/.config/rclone/rclone.conf

echo "==> Verifying Spaces read + write..."
PROBE="spaces:${BUCKET}/.install-write-probe"
if ! rclone lsd "spaces:${BUCKET}" >/dev/null 2>&1; then
  echo "ERROR: Spaces bucket unreadable with the configured credentials/endpoint." >&2
  echo "       Fix SPACES_* and re-run; until then bucket pushes fail and alert," >&2
  echo "       and deploys stop at their pre-migration backup." >&2
  exit 1
fi
if ! echo "install-probe" | rclone rcat "$PROBE" >/dev/null 2>&1; then
  echo "ERROR: Spaces bucket not writable — the key lacks write permission." >&2
  echo "       Grant the key Read/Write and re-run; until then bucket pushes fail" >&2
  echo "       and alert, and deploys stop at their pre-migration backup." >&2
  exit 1
fi
rclone deletefile "$PROBE" >/dev/null 2>&1 || true
echo "    Spaces read + write OK."

echo "==> Installing systemd units..."
render_systemd_unit() {  # <template> <destination>
  sed -e "s|__APP_NAME__|$APP_NAME|g" -e "s|__REPO_DIR__|$REPO_DIR|g" "$1" > "$2"
  chmod 644 "$2"
}
# deploy.sh renders these on every deploy too; rendering them here as well covers a
# server whose last deploy predates them.
for unit in backup.service backup.timer restore-drill.service restore-drill.timer \
  alert-restore-drill.service; do
  render_systemd_unit "scripts/systemd/$unit" "/etc/systemd/system/$APP_NAME-$unit"
done
systemctl daemon-reload
systemctl enable --now "$APP_NAME-backup.timer" "$APP_NAME-restore-drill.timer"
echo "==> Done. Run a backup now:  systemctl start $APP_NAME-backup.service"
echo "    and then the drill:      systemctl start $APP_NAME-restore-drill.service"
echo "    Logs: /var/log/$APP_NAME/backup.log, /var/log/$APP_NAME/restore-drill.log"
