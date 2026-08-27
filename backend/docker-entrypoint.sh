#!/bin/sh
# One image, two roles.
#
# Coolify's "custom start command" field is applied inconsistently for Dockerfile
# builds, and a worker that silently boots as a second API is a bad failure: the
# stack looks healthy, ingest returns 202, and nothing ever writes to Postgres.
# An environment variable is the one lever that reliably works, so the role is
# selected here rather than by overriding the command.
set -e

case "${APP_ROLE:-api}" in
    api)
        exec uvicorn app.main:app \
            --host 0.0.0.0 --port 8000 --proxy-headers
        ;;
    worker)
        exec arq app.workers.consumer.WorkerSettings
        ;;
    *)
        echo "APP_ROLE must be 'api' or 'worker', got '${APP_ROLE}'" >&2
        exit 1
        ;;
esac
