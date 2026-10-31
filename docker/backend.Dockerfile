FROM python:3.12-slim

# The app runs as this unprivileged account, never as root. Fixed ids keep the owner of
# the files it writes to the uploads volume the same across rebuilds, and
# scripts/deploy.sh hands that volume to the same uid (BACKEND_UID).
RUN groupadd --system --gid 10001 app \
    && useradd --system --no-log-init --uid 10001 --gid app app

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
# A loop service runs a scheduled job on a host without systemd timers; nothing starts
# one by default (ai/project.md, Scheduled Jobs).
COPY docker/job-loop.sh docker/job-loop.sh

# The uploads_data volume mounts here. Docker gives a new, empty volume this directory's
# owner; scripts/deploy.sh hands over one that already holds files.
RUN install -d -o app -g app src_back/uploads

# Production leaves the source owned by root, so the process serving it cannot change
# it. The dev stack builds with SOURCE_OWNER=app (docker-compose.override.yml), because
# Compose's file watch writes and deletes files, and creates them in every synced
# directory, as the container's user.
ARG SOURCE_OWNER=root
RUN if [ "$SOURCE_OWNER" != root ]; then \
      chown -R "$SOURCE_OWNER:$SOURCE_OWNER" src_back migrations docker; \
    fi

USER app

EXPOSE 5000

CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "src_back.app:create_app()"]
