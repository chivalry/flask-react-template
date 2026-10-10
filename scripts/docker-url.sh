#!/bin/sh
# Wait for the dev frontend to answer, then print its URL.
#
# The host port is read back from Docker, so whatever FRONTEND_PORT scripts/up.sh or
# scripts/worktree-setup.sh settled on is picked up automatically.
# Usage: npm run docker:url
set -eu

timeout_seconds=60

# `|| true` so that a stopped stack (compose exits non-zero) reaches the check
# below instead of tripping `set -e` with no output at all.
port=$(docker compose port frontend 5173 2>/dev/null | head -n 1 | sed 's/.*://' || true)

if [ -z "$port" ]; then
  echo "==> No published port for frontend; the stack is not running."
  echo "    Start it with: npm run docker:up"
  exit 0
fi

url="http://localhost:$port"

echo "==> Waiting for $url ..."
i=0
while [ "$i" -lt "$timeout_seconds" ]; do
  if curl --silent --fail --output /dev/null "$url"; then
    echo "==> Frontend is ready at $url"
    exit 0
  fi
  sleep 1
  i=$((i + 1))
done

echo "==> $url did not respond within ${timeout_seconds}s; the stack may still be starting."
echo "    Check: docker compose logs -f frontend"
