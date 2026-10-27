#!/usr/bin/env bash
# Build the backend image as production builds it and as the dev stack builds it, and
# check who runs the app and who owns its files: the unprivileged app user (uid 10001)
# runs every container; the production source belongs to root, so the process serving
# it cannot change it; all of the dev source belongs to the app user, as Compose's file
# watch needs; a new, empty volume on the uploads directory is writable by the app
# user; and one that already holds root's files is not, until the chown that
# scripts/deploy.sh runs hands it over. It needs a running Docker daemon; without one
# it exits 77, which scripts/tests/run-all.sh counts as a skip outside CI. It runs
# under macOS's bash 3.2 and on Linux.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."
docker info > /dev/null 2>&1 ||
  { echo 'test-backend-image.sh needs a running Docker daemon.' >&2; exit 77; }

IMAGE="test-backend-image-$$"
NEW_VOLUME="test-backend-image-new-$$"
OLD_VOLUME="test-backend-image-old-$$"
cleanup() {
  docker volume rm -f "$NEW_VOLUME" "$OLD_VOLUME" > /dev/null 2>&1 || true
  docker image rm -f "$IMAGE:production" "$IMAGE:development" > /dev/null 2>&1 || true
}
trap cleanup EXIT

fail() {
  echo "$1" >&2
  exit 1
}

docker build --quiet --file docker/backend.Dockerfile --tag "$IMAGE:production" . \
  > /dev/null
# The dev stack's build argument (docker-compose.override.yml); watchdog is irrelevant.
docker build --quiet --file docker/backend.Dockerfile --build-arg SOURCE_OWNER=app \
  --tag "$IMAGE:development" . > /dev/null

# run_in TAG COMMAND [ARG...] -> run COMMAND in a throwaway container of the image, as
# the image's own user, from its working directory, /app.
run_in() {
  local tag="$1" command="$2"
  shift 2
  docker run --rm --entrypoint "$command" "$IMAGE:$tag" "$@"
}

# app_can_write VOLUME -> the app user can create a file in VOLUME, mounted on the
# production image's uploads directory.
app_can_write() {
  docker run --rm -v "$1:/app/src_back/uploads" --entrypoint touch \
    "$IMAGE:production" src_back/uploads/probe 2> /dev/null
}

for tag in production development; do
  [ "$(run_in "$tag" id -u)" = 10001 ] ||
    fail "The $tag image does not run as uid 10001."
  [ "$(run_in "$tag" stat -c %U src_back/uploads)" = app ] ||
    fail "The app user does not own src_back/uploads in the $tag image."
  # Both stacks start the backend with /bin/sh docker/entrypoint.sh.
  run_in "$tag" sh -n docker/entrypoint.sh ||
    fail "The app user cannot read docker/entrypoint.sh in the $tag image."
done
for path in src_back src_back/app.py migrations docker docker/entrypoint.sh; do
  [ "$(run_in production stat -c %U "$path")" = root ] ||
    fail "root does not own $path in the production image."
done
if run_in production touch src_back/probe 2> /dev/null; then
  fail 'The app user can write the production source.'
fi
# File watch writes, deletes, and creates files in every synced directory.
UNOWNED=$(run_in development find src_back migrations docker ! -user app) ||
  fail 'find failed in the development image.'
[ -z "$UNOWNED" ] ||
  fail "The app user does not own these in the development image: $UNOWNED"

# Docker gives a new, empty named volume the owner of the image directory it mounts on.
docker volume create "$NEW_VOLUME" > /dev/null
app_can_write "$NEW_VOLUME" || fail 'The app user cannot write to a new uploads volume.'

# A volume that already holds root's files keeps root as its owner until the chown
# scripts/deploy.sh runs hands it over.
docker run --rm -v "$OLD_VOLUME:/uploads" alpine touch /uploads/old-upload
if app_can_write "$OLD_VOLUME"; then
  fail 'The app user could write to a volume that root owns.'
fi
docker run --rm -v "$OLD_VOLUME:/uploads" alpine chown -R 10001:10001 /uploads
app_can_write "$OLD_VOLUME" ||
  fail "deploy.sh's chown does not hand an old uploads volume to the app user."

echo 'Backend image checks passed.'
