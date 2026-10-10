#!/usr/bin/env bash
# Warn before any Let's Encrypt certificate on this host expires.
#
# Belt-and-braces companion to the certbot OnFailure alert. That alert fires when
# certbot.service exits non-zero; this catches the cases it cannot — the timer being
# disabled or dead, a renewal that "succeeds" without nginx picking it up, or a cert
# nobody is renewing at all.
#
# Logs to /var/log/<APP_NAME>/cert-check.log and exits non-zero when any cert is
# inside the warning window, so systemd records a failure too.
# Usage: cert-check.sh [warn_days]   (default 21)
set -uo pipefail

WARN_DAYS="${1:-21}"
LIVE_DIR=/etc/letsencrypt/live

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"

get() { grep -E "^$1=" "$REPO_DIR/.env" 2>/dev/null | tail -1 | cut -d= -f2- || true; }

APP_NAME="$(get APP_NAME)"
if [ -z "$APP_NAME" ]; then
  echo "ERROR: APP_NAME is empty in $REPO_DIR/.env; cannot locate the log directory." >&2
  exit 1
fi
LOG_DIR="/var/log/$APP_NAME"
mkdir -p "$LOG_DIR"

log() {
  printf '%s [cert-check] %s\n' "$(date -u +%FT%TZ)" "$*" \
    | tee -a "$LOG_DIR/cert-check.log"
}

shopt -s nullglob
CERTS=("$LIVE_DIR"/*/cert.pem)
shopt -u nullglob

if [ ${#CERTS[@]} -eq 0 ]; then
  log "FAILURE: no certificates found under $LIVE_DIR"
  bash "$SCRIPT_DIR/alert.sh" "$APP_NAME: no TLS certificates found" \
    "Nothing under $LIVE_DIR on $(hostname). TLS is probably broken."
  exit 1
fi

PROBLEMS=()

for cert in "${CERTS[@]}"; do
  name="$(basename "$(dirname "$cert")")"
  expiry="$(openssl x509 -enddate -noout -in "$cert" 2>/dev/null | cut -d= -f2)"

  if [ -z "$expiry" ]; then
    log "FAILURE: $name — could not read expiry from $cert"
    PROBLEMS+=("$name: unreadable certificate")
    continue
  fi

  if openssl x509 -checkend $((WARN_DAYS * 86400)) -noout -in "$cert" \
    >/dev/null 2>&1; then
    log "OK: $name expires $expiry"
  elif openssl x509 -checkend 0 -noout -in "$cert" >/dev/null 2>&1; then
    log "FAILURE: $name expires $expiry — inside the ${WARN_DAYS}-day window"
    PROBLEMS+=("$name expires $expiry (under $WARN_DAYS days)")
  else
    log "FAILURE: $name EXPIRED at $expiry"
    PROBLEMS+=("$name ALREADY EXPIRED at $expiry")
  fi
done

if [ ${#PROBLEMS[@]} -eq 0 ]; then
  log "SUCCESS: all ${#CERTS[@]} certificate(s) valid beyond $WARN_DAYS days"
  exit 0
fi

BODY="$(printf '%s\n' "${PROBLEMS[@]}")
Host: $(hostname)
Check: certbot certificates && journalctl -u certbot.service -n 50"

bash "$SCRIPT_DIR/alert.sh" "$APP_NAME: TLS certificate needs attention" "$BODY"
exit 1
