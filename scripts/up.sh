#!/bin/sh
# Start containers. In development, auto-assigns free host ports, then builds the images
# from the working tree and watches it (develop.watch in docker-compose.override.yml),
# so saved edits reach the running containers.
#
# Starting values come from .env, so ports shifted by scripts/worktree-setup.sh are
# respected, falling back to .env.example. A stack that is already running keeps
# its ports: its own listeners would otherwise look "in use" and get bumped.

set -e

[ -f .env ] || cp .env.example .env

# read_env KEY FILE -> value of the last KEY= line in FILE, or empty.
read_env() {
  grep -E "^$1=" "$2" 2>/dev/null | tail -1 | cut -d= -f2- | tr -d '[:space:]'
}

flask_env=$(read_env FLASK_ENV .env)
already_running=$(docker compose ps -q 2>/dev/null)

if [ "$flask_env" != "production" ] && [ -z "$already_running" ]; then
  port_in_use() {
    lsof -i TCP:"$1" -sTCP:LISTEN -n -P 2>/dev/null | grep -q LISTEN
  }

  next_free_port() {
    port=$1
    while port_in_use "$port"; do
      port=$((port + 1))
    done
    echo "$port"
  }

  # default_port KEY FALLBACK -> .env value, else .env.example value, else FALLBACK.
  default_port() {
    value=$(read_env "$1" .env)
    [ -n "$value" ] || value=$(read_env "$1" .env.example)
    echo "${value:-$2}"
  }

  db_port=$(next_free_port "$(default_port DB_PORT 5432)")
  backend_port=$(next_free_port "$(default_port BACKEND_PORT 5000)")
  frontend_port=$(next_free_port "$(default_port FRONTEND_PORT 5174)")

  # Older .env files predate some keys; add them so the sed below has a line to edit.
  for key in DB_PORT BACKEND_PORT FRONTEND_PORT VITE_API_URL PUBLIC_BASE_URL; do
    grep -qE "^$key=" .env || echo "$key=" >> .env
  done

  tmp=$(mktemp)
  sed "s/^DB_PORT=.*/DB_PORT=${db_port}/" .env \
    | sed "s/^BACKEND_PORT=.*/BACKEND_PORT=${backend_port}/" \
    | sed "s/^FRONTEND_PORT=.*/FRONTEND_PORT=${frontend_port}/" \
    | sed "s|^VITE_API_URL=.*|VITE_API_URL=http://localhost:${backend_port}|" \
    | sed "s|^PUBLIC_BASE_URL=\$|PUBLIC_BASE_URL=http://localhost:${frontend_port}|" \
    | sed -E "s|^(PUBLIC_BASE_URL=http://localhost:)[0-9]+(/?)\$|\1${frontend_port}\2|" \
    | sed -E "s|^(DATABASE_URL=.*@localhost):[0-9]+/|\1:${db_port}/|" > "$tmp"
  mv "$tmp" .env

  echo "Port assignment:"
  echo "  DB_PORT         = ${db_port}"
  echo "  BACKEND_PORT    = ${backend_port}"
  echo "  FRONTEND_PORT   = ${frontend_port}"
  echo "  VITE_API_URL    = http://localhost:${backend_port}"
  echo "  PUBLIC_BASE_URL = $(read_env PUBLIC_BASE_URL .env)"
elif [ -n "$already_running" ]; then
  echo "Stack already running; keeping the ports in .env."
fi

# Production starts as it always has: no build, no watch.
if [ "$flask_env" = "production" ]; then
  docker compose up "$@"
  exit
fi

# Compose cannot watch a detached stack, and --wait implies detached, so say so.
detached=
for arg in "$@"; do
  case "$arg" in
    -d | --detach | --wait) detached=1 ;;
  esac
done

if [ -n "$detached" ]; then
  echo "Starting detached, so not watching: saved edits will not reach the containers."
  echo "  Watch them with: docker compose watch --no-up"
  docker compose up --build "$@"
else
  docker compose up --build --watch "$@"
fi
