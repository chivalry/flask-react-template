#!/bin/sh
set -e

echo "Running database migrations..."
flask --app src_back.app db upgrade

# A non-zero exit here stops the container: a seed that cannot run is a deployment
# failure, not something to log and continue past. Seeds skip optional work themselves.
echo "Seeding database..."
python -m src_back.seed

# The dev stack (FLASK_ENV=development in docker-compose.yml) runs Flask's development
# server. Its reloader applies the edits Compose syncs in, including added and deleted
# modules, since the dev build installs watchdog for it, and keeps serving through an
# edit that breaks an import. Debug mode and its debugger stay off because the backend
# port is published on every interface. Every other stack runs gunicorn.
if [ "${FLASK_ENV:-}" = development ]; then
  echo "Starting the Flask development server..."
  exec flask --app src_back.app run --host 0.0.0.0 --port 5000 --reload --no-debugger
fi

echo "Starting gunicorn..."
exec gunicorn \
  --bind 0.0.0.0:5000 \
  --workers "${GUNICORN_WORKERS:-2}" \
  --access-logfile - \
  "src_back.app:create_app()"
