#!/bin/sh
set -e

echo "Running database migrations..."
flask --app src_back.app db upgrade

# A non-zero exit here stops the container: a seed that cannot run is a deployment
# failure, not something to log and continue past. Seeds skip optional work themselves.
echo "Seeding database..."
python -m src_back.seed

echo "Starting gunicorn..."
exec gunicorn \
  --bind 0.0.0.0:5000 \
  --workers "${GUNICORN_WORKERS:-2}" \
  --access-logfile - \
  "src_back.app:create_app()"
