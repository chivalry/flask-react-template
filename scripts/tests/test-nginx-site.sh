#!/usr/bin/env bash
# Run scripts/nginx-ssl.conf.template in a real nginx, rendered for two apps on one
# host as scripts/deploy.sh renders it, beside stub upstreams and a throwaway
# certificate per domain. It checks that nginx accepts both sites; that a page, an API
# answer, and nginx's own 429 all carry the four security headers; that sign-in POSTs
# are throttled per app with a JSON 429, while GETs and other API POSTs never are; and
# that the throttled location forwards the same proxy headers as the other API paths.
# It needs a running Docker daemon, curl, and openssl; without them it exits 77, which
# scripts/tests/run-all.sh counts as a skip outside CI. It runs under macOS's bash 3.2
# and on Linux.
set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
for tool in docker curl openssl; do
  command -v "$tool" > /dev/null ||
    { echo "test-nginx-site.sh needs $tool." >&2; exit 77; }
done
docker info > /dev/null 2>&1 ||
  { echo 'test-nginx-site.sh needs a running Docker daemon.' >&2; exit 77; }

# The server runs Ubuntu's nginx package; the production frontend image's nginx, which
# the repository already pulls, stands in for it.
IMAGE=nginx:1.27-alpine
CONTAINER="test-nginx-site-$$"
TEST_DIR=$(mktemp -d)
cleanup() {
  docker rm -f "$CONTAINER" > /dev/null 2>&1 || true
  rm -rf "$TEST_DIR"
}
trap cleanup EXIT
mkdir -p "$TEST_DIR/conf.d"

fail() {
  echo "$1" >&2
  exit 1
}

# Two apps on one host, each rendered as deploy.sh renders the template and each with
# its own certificate. Both proxy to the stub upstreams below.
for app in alpha beta; do
  sed -e "s|__APP_NAME__|$app|g" -e "s|__DOMAIN__|$app.test|g" \
    -e 's|__BACKEND_PORT__|5000|g' -e 's|__FRONTEND_HOST_PORT__|8080|g' \
    "$REPO_DIR/scripts/nginx-ssl.conf.template" > "$TEST_DIR/conf.d/$app.conf"
  if grep -Eq '__[A-Z_]+__' "$TEST_DIR/conf.d/$app.conf"; then
    fail "A placeholder is left in the $app site; render it as deploy.sh does."
  fi
  mkdir -p "$TEST_DIR/letsencrypt/live/$app.test"
  openssl req -x509 -newkey rsa:2048 -nodes -days 1 -subj "/CN=$app.test" \
    -keyout "$TEST_DIR/letsencrypt/live/$app.test/privkey.pem" \
    -out "$TEST_DIR/letsencrypt/live/$app.test/fullchain.pem" > /dev/null 2>&1
done
# Stand-ins for the backend and the frontend container on their loopback ports. The
# backend answers with the proxy headers it received.
cat > "$TEST_DIR/conf.d/upstreams.conf" <<'NGINX'
server {
    listen 127.0.0.1:5000;
    location / {
        set $seen "$http_host|$http_x_real_ip|$http_x_forwarded_for";
        return 200 "$seen|$http_x_forwarded_proto";
    }
}
server {
    listen 127.0.0.1:8080;
    location / { return 200 'frontend'; }
}
NGINX

# run_nginx DOCKER-RUN-ARG... -> docker run with the sites and certificates mounted.
run_nginx() {
  docker run -v "$TEST_DIR/conf.d:/etc/nginx/conf.d:ro" \
    -v "$TEST_DIR/letsencrypt:/etc/letsencrypt:ro" "$@"
}
run_nginx --rm "$IMAGE" nginx -t > "$TEST_DIR/nginx-t.log" 2>&1 || {
  cat "$TEST_DIR/nginx-t.log" >&2
  fail 'nginx rejected the rendered sites.'
}
run_nginx -d --name "$CONTAINER" -p 127.0.0.1::443 "$IMAGE" > /dev/null
PORT=$(docker port "$CONTAINER" 443/tcp | head -1 | sed 's/.*://')

# fetch APP PATH [CURL-ARG...] -> print the response status; the headers and body land
# in $TEST_DIR/headers and $TEST_DIR/body. --data '' makes the request a POST.
fetch() {
  local app="$1" path="$2" status
  shift 2
  : > "$TEST_DIR/raw-headers"
  status=$(curl -sk --resolve "$app.test:$PORT:127.0.0.1" -D "$TEST_DIR/raw-headers" \
    -o "$TEST_DIR/body" -w '%{http_code}' "$@" "https://$app.test:$PORT$path") || true
  tr -d '\r' < "$TEST_DIR/raw-headers" > "$TEST_DIR/headers"
  echo "$status"
}

# assert_header NAME VALUE -> the last response carried exactly that header line.
assert_header() {
  grep -iqxF "$1: $2" "$TEST_DIR/headers" ||
    fail "The response to the last request lacks '$1: $2'."
}

# assert_security_headers -> the last response carried all four security headers.
assert_security_headers() {
  assert_header Strict-Transport-Security 'max-age=31536000'
  assert_header X-Content-Type-Options nosniff
  assert_header Referrer-Policy strict-origin-when-cross-origin
  assert_header Content-Security-Policy "frame-ancestors 'none'"
}

attempt=0
until [ "$(fetch alpha /)" = 200 ]; do
  attempt=$((attempt + 1))
  if [ "$attempt" -ge 50 ]; then
    docker logs "$CONTAINER" >&2
    fail 'nginx never answered.'
  fi
  sleep 0.2
done
assert_security_headers
[ "$(fetch alpha /api/health)" = 200 ] || fail 'An API GET did not reach the backend.'
assert_security_headers

# Six sign-in POSTs pass at once, one plus a burst of five; the next five get a JSON
# 429 that carries the security headers too. One token returns every six seconds, so
# the count holds while the eleven requests leave within about a second; local curls
# take milliseconds.
statuses=''
for attempt in 1 2 3 4 5 6 7 8 9 10 11; do
  statuses="$statuses $(fetch alpha /api/v1/auth/login --data '')"
done
[ "$statuses" = ' 200 200 200 200 200 200 429 429 429 429 429' ] ||
  fail "Sign-in POSTs answered$statuses, not six 200s and then five 429s."
assert_security_headers
assert_header Content-Type application/json
grep -qxF '{"error": "Too many attempts. Try again in a minute."}' "$TEST_DIR/body" ||
  fail 'The 429 does not carry the JSON error envelope.'

# GETs never count, so /me keeps answering, and POSTs elsewhere under /api are not
# throttled. Each app counts its own attempts, so beta's first sign-in POST passes, and
# the throttled location forwards what the backend sees from any other API path.
for attempt in 1 2 3 4 5 6 7 8 9 10 11; do
  [ "$(fetch alpha /api/v1/auth/me)" = 200 ] || fail 'A sign-in GET was throttled.'
  [ "$(fetch alpha /api/v1/users --data '')" = 200 ] ||
    fail 'A POST outside /api/v1/auth/ was throttled.'
done
[ "$(fetch beta /api/health)" = 200 ] || fail "An API GET to the second app failed."
API_PROXY_HEADERS=$(cat "$TEST_DIR/body")
[ "$(fetch beta /api/v1/auth/login --data '')" = 200 ] ||
  fail "One app's sign-in attempts throttled another's."
[ "$(cat "$TEST_DIR/body")" = "$API_PROXY_HEADERS" ] ||
  fail 'The throttled location forwards other proxy headers than the API location.'

echo 'nginx site checks passed.'
