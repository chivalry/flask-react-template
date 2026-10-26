FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# The dev stack sets this to watchdog (docker-compose.override.yml): Flask's reloader uses
# it when installed and then sees modules being added and deleted, which its fallback stat
# reloader misses. Production builds leave it empty and install nothing more.
ARG DEVELOPMENT_PACKAGES=
RUN if [ -n "$DEVELOPMENT_PACKAGES" ]; then \
      pip install --no-cache-dir $DEVELOPMENT_PACKAGES; \
    fi

COPY src_back/ ./src_back/
COPY migrations/ ./migrations/
COPY docker/entrypoint.sh docker/entrypoint.sh

EXPOSE 5000

CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "src_back.app:create_app()"]
