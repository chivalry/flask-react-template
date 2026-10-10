#!/bin/sh
set -e

echo "Running database migrations..."
flask --app src_back.app db upgrade

echo "Seeding database..."
python -m src_back.seed || echo "Seed skipped or failed - continuing."

echo "Starting gunicorn..."
exec gunicorn \
  --bind 0.0.0.0:5000 \
  --workers "${GUNICORN_WORKERS:-2}" \
  --access-logfile - \
  "src_back.app:create_app()"
