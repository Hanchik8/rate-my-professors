#!/bin/sh
# Runs before the app starts: wait for the database, apply migrations.
set -e

if [ -n "$DATABASE_URL" ]; then
  echo "waiting for database..."
  python - <<'PY'
import os, sys, time
import psycopg
for attempt in range(60):
    try:
        psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=3).close()
        sys.exit(0)
    except Exception as exc:
        time.sleep(1)
print("database is not reachable", file=sys.stderr)
sys.exit(1)
PY
fi

if [ "${RUN_MIGRATIONS:-1}" = "1" ]; then
  python manage.py migrate --noinput
fi

# static files are already collected in the image; set COLLECTSTATIC=1 to redo it
if [ "${COLLECTSTATIC:-0}" = "1" ]; then
  python manage.py collectstatic --noinput -v0
fi

exec "$@"
