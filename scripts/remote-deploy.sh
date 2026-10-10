#!/usr/bin/env bash
# SSH into the server and run scripts/deploy.sh there. Runs on a laptop.
# Usage:
#   npm run deploy                      # host from DEPLOY_HOST
#   npm run deploy -- ubuntu@1.2.3.4    # explicit host (any ssh target or alias)
#
# The clone on the server is assumed to live at ~/<APP_NAME>, where APP_NAME is read
# from the local .env (falling back to .env.example), matching what provision.sh wrote.
set -euo pipefail

TARGET="${1:-${DEPLOY_HOST:?set DEPLOY_HOST or pass a host}}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"

get() { grep -E "^$1=" "$2" 2>/dev/null | tail -1 | cut -d= -f2- || true; }

APP_NAME="$(get APP_NAME "$REPO_DIR/.env")"
[ -n "$APP_NAME" ] || APP_NAME="$(get APP_NAME "$REPO_DIR/.env.example")"
if [ -z "$APP_NAME" ]; then
  echo "ERROR: APP_NAME is not set in $REPO_DIR/.env or .env.example."
  exit 1
fi

echo "==> Deploying $APP_NAME to $TARGET..."
# APP_NAME is resolved here on purpose; the quoted ~ is left for the remote shell.
# shellcheck disable=SC2029
ssh "$TARGET" "bash ~/$APP_NAME/scripts/deploy.sh"
