#!/usr/bin/env bash
# Obtain the first Let's Encrypt certificate for DOMAIN (read from .env).
# Run on the server AFTER DNS has propagated and BEFORE the first deploy.
# Usage: bash scripts/certbot-setup.sh [--email <addr>]
#   The registration address comes from CERTBOT_EMAIL in .env, or from --email.
#
# Uses --standalone for the FIRST issuance only. On a freshly provisioned host
# provision.sh has removed the default site, so nginx is serving no server block at
# all and the --nginx authenticator has nothing to insert its challenge into.
# Standalone binds port 80 itself, which is why nginx is stopped just below.
#
# That choice must NOT survive into renewals: unattended renewals run while nginx
# holds :80 permanently, so standalone can never rebind and every renewal fails with
# "Could not bind TCP port 80". In the project this script was ported from, that
# expired the production certificate after 66 consecutive silent failures. The renewal
# config is therefore switched to the nginx authenticator immediately after issuance
# and verified before this script reports success.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"

get() { grep -E "^$1=" "$REPO_DIR/.env" 2>/dev/null | tail -1 | cut -d= -f2- || true; }

DOMAIN="$(get DOMAIN)"
EMAIL="$(get CERTBOT_EMAIL)"

while [ $# -gt 0 ]; do
  case "$1" in
    --email)
      EMAIL="${2:-}"
      if [ -z "$EMAIL" ]; then
        echo "ERROR: --email requires an address."
        exit 1
      fi
      shift 2
      ;;
    --email=*)
      EMAIL="${1#--email=}"
      shift
      ;;
    *)
      echo "usage: bash scripts/certbot-setup.sh [--email <addr>]"
      exit 1
      ;;
  esac
done

if [ -z "$DOMAIN" ]; then
  echo "ERROR: DOMAIN is empty in $REPO_DIR/.env."
  exit 1
fi
if [ -z "$EMAIL" ]; then
  echo "ERROR: no registration email."
  echo "       Set CERTBOT_EMAIL in $REPO_DIR/.env or pass --email <addr>."
  exit 1
fi

echo "==> Verifying DNS for $DOMAIN resolves to this machine..."
RESOLVED=$(dig +short "$DOMAIN" | tail -1)
MY_IP=$(curl -s https://api.ipify.org)

if [ "$RESOLVED" != "$MY_IP" ]; then
  echo "ERROR: $DOMAIN resolves to '$RESOLVED' but this machine is $MY_IP"
  echo "       Wait for DNS to propagate and try again."
  exit 1
fi

echo "==> Stopping any service on port 80..."
sudo systemctl stop nginx 2>/dev/null || true
sudo systemctl stop apache2 2>/dev/null || true

echo "==> Requesting certificate..."
sudo certbot certonly --standalone -d "$DOMAIN" \
  --non-interactive --agree-tos -m "$EMAIL"

RENEWAL_CONF="/etc/letsencrypt/renewal/$DOMAIN.conf"
echo "==> Switching renewal to the nginx authenticator..."
sudo sed -i 's/^authenticator = standalone$/authenticator = nginx/' "$RENEWAL_CONF"

if ! sudo grep -qx 'authenticator = nginx' "$RENEWAL_CONF"; then
  echo "ERROR: failed to set the nginx authenticator in $RENEWAL_CONF"
  echo "       Renewals would fail to bind port 80 once nginx is running."
  exit 1
fi

# Leave the host as it was found: nginx was stopped above so standalone could bind :80.
echo "==> Starting nginx again..."
sudo systemctl start nginx

echo ""
echo "==> Certificate obtained."
echo "    fullchain: /etc/letsencrypt/live/$DOMAIN/fullchain.pem"
echo "    privkey:   /etc/letsencrypt/live/$DOMAIN/privkey.pem"
echo ""
echo "    Renewal authenticator: nginx (verified)."
echo "    After the first deploy installs the nginx site config, confirm renewal works:"
echo "      certbot renew --dry-run"
