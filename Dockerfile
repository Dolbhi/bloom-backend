# Bloom API image: used by docker compose locally AND by Render in production.
FROM python:3.13-slim

# Don't write .pyc files; print logs straight away (so Render shows them live)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# GeoDjango needs GDAL, GEOS and PROJ system libraries (Django's GIS install docs list these packages).
# This is the reason Render must use Docker: its native Python runtime can't install them.
RUN apt-get update \
 && apt-get install -y --no-install-recommends binutils libproj-dev gdal-bin \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python packages first, so Docker caches this layer until requirements.txt changes
COPY requirements.txt .
RUN pip install -r requirements.txt

# Copy the project code
COPY . .

# Run as a normal user, not root
RUN useradd --create-home appuser && chown -R appuser /app
USER appuser

EXPOSE 8000

# Production start (Render). docker-compose.yml overrides this with runserver for local dev.
CMD ["sh", "scripts/start.sh"]
