#!/bin/sh
set -e

echo "Running database migrations..."
flask --app src_back.app db upgrade

echo "Starting gunicorn..."
exec gunicorn \
  --bind 0.0.0.0:5000 \
  --workers 2 \
  --access-logfile - \
  "src_back.app:create_app()"
