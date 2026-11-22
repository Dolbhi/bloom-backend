#!/bin/sh
# Local dev start command (docker-compose.yml). Production uses scripts/start.sh instead.
set -e

python manage.py migrate --noinput
exec python manage.py runserver 0.0.0.0:8000
