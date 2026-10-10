#!/usr/bin/env bash
# Send an operational alert to the webhook configured in the server's .env.
# Usage: alert.sh "<subject>" "<body>"
#
# Reads ALERT_WEBHOOK_URL and optional ALERT_WEBHOOK_FORMAT (text|slack|discord,
# default text) from the .env beside the repo. Deliberately never echoes the URL,
# which is a secret. Logs every alert to /var/log/<APP_NAME>/alert.log.
#
# A missing or unreachable webhook is logged and returns 0 on purpose: an alert that
# cannot be delivered must not also mask the failure that triggered it. Callers decide
# their own exit status. The one exception is an empty APP_NAME, without which there
# is no log directory; that is a configuration error and exits 1.
set -uo pipefail

SUBJECT="${1:?usage: alert.sh <subject> <body>}"
BODY="${2:-}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"

get() { grep -E "^$1=" "$REPO_DIR/.env" 2>/dev/null | tail -1 | cut -d= -f2- || true; }

APP_NAME="$(get APP_NAME)"
if [ -z "$APP_NAME" ]; then
  echo "ERROR: APP_NAME is empty in $REPO_DIR/.env; cannot locate the alert log." >&2
  exit 1
fi
LOG_DIR="/var/log/$APP_NAME"
mkdir -p "$LOG_DIR"

log() {
  printf '%s [alert] %s\n' "$(date -u +%FT%TZ)" "$*" >>"$LOG_DIR/alert.log"
}

URL="$(get ALERT_WEBHOOK_URL)"
FORMAT="$(get ALERT_WEBHOOK_FORMAT)"; FORMAT="${FORMAT:-text}"

log "$SUBJECT — $BODY"

if [ -z "$URL" ]; then
  log "WARN: ALERT_WEBHOOK_URL not set in $REPO_DIR/.env; alert logged only"
  exit 0
fi

# Escape the message for safe embedding in a JSON string payload.
json_escape() {
  printf '%s' "$1" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))'
}

case "$FORMAT" in
  slack)
    PAYLOAD="{\"text\": $(json_escape "$SUBJECT"$'\n'"$BODY")}"
    ARGS=(-H 'Content-Type: application/json' -d "$PAYLOAD")
    ;;
  discord)
    PAYLOAD="{\"content\": $(json_escape "$SUBJECT"$'\n'"$BODY")}"
    ARGS=(-H 'Content-Type: application/json' -d "$PAYLOAD")
    ;;
  text)
    ARGS=(-H "Title: $SUBJECT" -d "$BODY")
    ;;
  *)
    log "ERROR: unknown ALERT_WEBHOOK_FORMAT '$FORMAT' (use text, slack, or discord)"
    exit 0
    ;;
esac

if curl -fsS --max-time 15 "${ARGS[@]}" "$URL" >/dev/null 2>&1; then
  log "delivered via $FORMAT webhook"
else
  log "WARN: webhook delivery failed (format=$FORMAT); alert logged only"
fi

exit 0
