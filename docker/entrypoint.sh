#!/bin/sh
set -e
# Only the web service sets RUN_MIGRATIONS=1 (worker/beat must not race on schema changes).
if [ "${RUN_MIGRATIONS:-0}" = "1" ]; then
  # Dev convenience: generate migrations on first boot. In production, commit them and leave this off.
  if [ "${AUTO_MAKEMIGRATIONS:-0}" = "1" ]; then
    python manage.py makemigrations accounts venues bookings payments --noinput
  fi
  python manage.py migrate --noinput
  python manage.py collectstatic --noinput
fi
exec "$@"
