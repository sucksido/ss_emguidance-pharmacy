#!/bin/sh
# Applies migrations, then hands over to the CMD (uvicorn by default).
# Compose already waits for the database healthcheck; the retry loop covers
# the window where Postgres accepts connections but is still finishing init.
set -e

if [ "${SKIP_MIGRATIONS:-0}" != "1" ]; then
  n=0
  until alembic upgrade head; do
    n=$((n + 1))
    if [ "$n" -ge 10 ]; then
      echo "migrations failed after $n attempts" >&2
      exit 1
    fi
    echo "database not ready, retrying migrations in 2s ($n/10)" >&2
    sleep 2
  done
fi

exec "$@"
