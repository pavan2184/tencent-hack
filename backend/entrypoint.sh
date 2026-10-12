#!/bin/sh
# One image, one role per container: ROLE=api|worker|beat|migrate|seed.
set -eu

ROLE=${ROLE:-api}
API_HOST=${API_HOST:-0.0.0.0}
API_PORT=${API_PORT:-8000}
LOG_LEVEL=${LOG_LEVEL:-info}

case "$ROLE" in
  api)
    exec uvicorn app.main:app --host "$API_HOST" --port "$API_PORT" --log-level "$LOG_LEVEL"
    ;;
  worker)
    exec celery -A app.celery_app.celery_app worker \
      -Q q.ingest,q.sync,q.verify,q.maintenance \
      --loglevel="$LOG_LEVEL" \
      --concurrency="${CELERY_CONCURRENCY:-2}"
    ;;
  beat)
    # /app is read-only for the non-root user; keep the schedule state in /tmp.
    exec celery -A app.celery_app.celery_app beat \
      --loglevel="$LOG_LEVEL" \
      --schedule /tmp/celerybeat-schedule
    ;;
  migrate)
    exec python -m app.db.migrate
    ;;
  seed)
    exec python -m app.seed
    ;;
  *)
    echo "entrypoint: unknown ROLE '$ROLE' (expected api|worker|beat|migrate|seed)" >&2
    exit 1
    ;;
esac
