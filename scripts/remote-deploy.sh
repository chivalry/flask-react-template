#!/usr/bin/env bash
# SSH into the server and run scripts/deploy.sh there. Runs on a laptop.
# Usage:
#   npm run deploy                          # production, host from DEPLOY_HOST
#   npm run deploy:staging                  # staging, host from DEPLOY_HOST
#   npm run deploy -- ubuntu@1.2.3.4        # explicit host (any ssh target or alias)
#   bash scripts/remote-deploy.sh [--environment <name>] [<host>]
#
# Production's clone on the server is ~/<APP_NAME>, where APP_NAME is read from the
# local .env (falling back to .env.example), matching what provision.sh wrote. Any other
# environment's clone is ~/<APP_NAME>-<environment>, whose own .env sets that APP_NAME
# (.env.staging.example). deploy.sh refuses a clone whose .env deploys another
# environment.
set -euo pipefail

usage() {
  echo 'usage: bash scripts/remote-deploy.sh [--environment <name>] [<host>]' >&2
  exit 1
}

ENVIRONMENT=production
TARGET=''
while [ $# -gt 0 ]; do
  case "$1" in
    --environment) [ $# -ge 2 ] || usage; ENVIRONMENT=$2; shift 2 ;;
    --environment=*) ENVIRONMENT=${1#--environment=}; shift ;;
    -*) usage ;;
    *) [ -z "$TARGET" ] || usage; TARGET=$1; shift ;;
  esac
done
# The name becomes part of a path and of the remote command line. Bash 3.2 matches a
# range such as a-z by the locale's collation, so the letters are spelled out.
case "$ENVIRONMENT" in
  '' | *[!abcdefghijklmnopqrstuvwxyz0123456789-]*) usage ;;
esac
TARGET="${TARGET:-${DEPLOY_HOST:-}}"
if [ -z "$TARGET" ]; then
  echo 'ERROR: set DEPLOY_HOST or pass a host.' >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"

get() { grep -E "^$1=" "$2" 2>/dev/null | tail -1 | cut -d= -f2- || true; }

APP_NAME="$(get APP_NAME "$REPO_DIR/.env")"
[ -n "$APP_NAME" ] || APP_NAME="$(get APP_NAME "$REPO_DIR/.env.example")"
if [ -z "$APP_NAME" ]; then
  echo "ERROR: APP_NAME is not set in $REPO_DIR/.env or .env.example."
  exit 1
fi
CLONE="$APP_NAME"
[ "$ENVIRONMENT" = production ] || CLONE="$APP_NAME-$ENVIRONMENT"

echo "==> Deploying $ENVIRONMENT ($CLONE) to $TARGET..."
# CLONE and ENVIRONMENT are resolved here on purpose; the quoted ~ is left for the
# remote shell.
# shellcheck disable=SC2029
ssh "$TARGET" "bash ~/$CLONE/scripts/deploy.sh --environment $ENVIRONMENT"
