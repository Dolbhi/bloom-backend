#!/bin/sh
# Production start command (Render runs this via the Dockerfile CMD).
set -e

# Apply any new migrations to Supabase before serving traffic.
# (Render's separate "pre-deploy command" is a paid feature, so the free tier does it here.)
python manage.py migrate --noinput

# Gather static files (Django admin CSS/JS) for WhiteNoise to serve
python manage.py collectstatic --noinput

# Render sets $PORT. Sync workers only: GDAL is not thread-safe, so use processes, not threads.
exec gunicorn config.wsgi:application \
  --bind 0.0.0.0:"${PORT:-8000}" \
  --workers "${WEB_CONCURRENCY:-2}" \
  --timeout 60
