#!/bin/sh
# Start containers. In development, auto-assigns free host ports before starting.

set -e

flask_env=$(grep -E '^FLASK_ENV=' .env 2>/dev/null | cut -d= -f2 | tr -d '[:space:]')

if [ "$flask_env" != "production" ]; then
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

  [ -f .env ] || cp .env.example .env

  backend_default=$(grep -E '^BACKEND_PORT=' .env.example \
    | cut -d= -f2 | tr -d '[:space:]')
  frontend_default=$(grep -E '^FRONTEND_PORT=' .env.example \
    | cut -d= -f2 | tr -d '[:space:]')
  backend_default=${backend_default:-5000}
  frontend_default=${frontend_default:-5174}

  backend_port=$(next_free_port "$backend_default")
  frontend_port=$(next_free_port "$frontend_default")

  tmp=$(mktemp)
  sed "s/^BACKEND_PORT=.*/BACKEND_PORT=${backend_port}/" .env \
    | sed "s/^FRONTEND_PORT=.*/FRONTEND_PORT=${frontend_port}/" \
    | sed "s|^VITE_API_URL=.*|VITE_API_URL=http://localhost:${backend_port}|" > "$tmp"
  mv "$tmp" .env

  echo "Port assignment:"
  echo "  BACKEND_PORT  = ${backend_port}"
  echo "  FRONTEND_PORT = ${frontend_port}"
  echo "  VITE_API_URL  = http://localhost:${backend_port}"
fi

docker compose up "$@"
