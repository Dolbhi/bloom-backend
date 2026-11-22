"""
Django settings for the Bloom API.

Everything that differs between local dev and Render comes from environment variables,
so the same code (and the same Docker image) runs in both places.
"""
import os
from datetime import timedelta
from pathlib import Path

import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent


def env_list(name, default=""):
    return [v.strip() for v in os.environ.get(name, default).split(",") if v.strip()]


def env_int(name, default):
    return int(os.environ.get(name, default))


# --- Core -------------------------------------------------------------------

SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]          # crash early if missing
DEBUG = os.environ.get("DJANGO_DEBUG", "False") == "True"

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")

# Render sets this automatically to e.g. bloom-api.onrender.com
RENDER_EXTERNAL_HOSTNAME = os.environ.get("RENDER_EXTERNAL_HOSTNAME")
if RENDER_EXTERNAL_HOSTNAME:
    ALLOWED_HOSTS.append(RENDER_EXTERNAL_HOSTNAME)
    CSRF_TRUSTED_ORIGINS.append(f"https://{RENDER_EXTERNAL_HOSTNAME}")   # lets Django admin log in over HTTPS

# --- Apps -------------------------------------------------------------------

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.gis",          # GeoDjango: PointField for submissions.location
    "django.contrib.postgres",     # trigram search + indexes
    "rest_framework",
    "rest_framework_simplejwt.token_blacklist",   # lets /auth/logout invalidate refresh tokens
    "drf_spectacular",
    "corsheaders",
    "core",
    "users",                       # custom user model (must exist before the first migrate)
    "plants",
    "submissions",
    "moderation",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",   # serves admin CSS/JS on Render
    "corsheaders.middleware.CorsMiddleware",
    "core.middleware.ApiTrailingSlashMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# --- Database ---------------------------------------------------------------
# One DATABASE_URL variable:
#   local  -> postgres://bloom:bloom@db:5432/bloom          (set in docker-compose.yml)
#   Render -> Supabase Session pooler string, port 5432      (set in Render env vars)
# engine= forces the PostGIS backend whatever the URL's scheme says.

DATABASES = {
    "default": dj_database_url.config(
        env="DATABASE_URL",
        engine="django.contrib.gis.db.backends.postgis",
        conn_max_age=600,           # reuse connections for 10 min instead of reconnecting per request
        conn_health_checks=True,    # drop a reused connection if the pooler closed it
        ssl_require=os.environ.get("DATABASE_SSL", str(not DEBUG)) == "True",
    )
}

# Only needed when running outside Docker and GeoDjango can't find GDAL/GEOS on its own
if os.environ.get("GDAL_LIBRARY_PATH"):
    GDAL_LIBRARY_PATH = os.environ["GDAL_LIBRARY_PATH"]
if os.environ.get("GEOS_LIBRARY_PATH"):
    GEOS_LIBRARY_PATH = os.environ["GEOS_LIBRARY_PATH"]

# --- Auth -------------------------------------------------------------------

AUTH_USER_MODEL = "users.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# --- Locale -----------------------------------------------------------------

LANGUAGE_CODE = "en-au"
TIME_ZONE = "Australia/Melbourne"
USE_I18N = True
USE_TZ = True   # store timestamps in UTC, convert for display

# --- Static + media files ---------------------------------------------------

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"       # only used by the "local" photo storage (dev)
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Production-only --------------------------------------------------------

if not DEBUG:
    # Render terminates HTTPS and forwards plain HTTP; this header tells Django the original was HTTPS
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

# --- CORS -------------------------------------------------------------------
# Native mobile apps don't need CORS. Only set this if a *browser* client (e.g. Expo web)
# calls the API: comma-separated origins like http://localhost:8081

CORS_ALLOWED_ORIGINS = env_list("CORS_ALLOWED_ORIGINS")

# --- Django REST Framework --------------------------------------------------

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        "rest_framework.authentication.SessionAuthentication",   # lets you click around /api/docs after admin login
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticatedOrReadOnly"],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_THROTTLE_RATES": {"auth": os.environ.get("AUTH_THROTTLE_RATE", "20/min")},
    "TEST_REQUEST_DEFAULT_FORMAT": "json",
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=env_int("JWT_ACCESS_MINUTES", 15)),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=env_int("JWT_REFRESH_DAYS", 7)),
    "UPDATE_LAST_LOGIN": True,
    "AUTH_HEADER_TYPES": ("Bearer",),
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Bloom API",
    "DESCRIPTION": "Backend for the Bloom plant-sighting app. Auth: `Authorization: Bearer <access>`.",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
    "ENUM_NAME_OVERRIDES": {
        "ModerationStatusEnum": "core.choices.ModerationStatus",
        "PlantStatusEnum": "core.choices.PlantStatus",
    },
}

# --- Bloom app rules --------------------------------------------------------
# ⚠️ Reputation numbers are placeholders (see bloom-project-agent/bloom-backend/01-features.md F8).
# Change them here or with env vars, no code changes needed.

BLOOM = {
    "REP_SUBMISSION_APPROVED": env_int("REP_SUBMISSION_APPROVED", 10),
    "REP_SUBMISSION_REJECTED": env_int("REP_SUBMISSION_REJECTED", -15),
    "REP_EDIT_APPROVED": env_int("REP_EDIT_APPROVED", 5),
    "REP_EDIT_REJECTED": env_int("REP_EDIT_REJECTED", -5),
    "REP_REVIEW_COMPLETED": env_int("REP_REVIEW_COMPLETED", 2),
    # Reputation that unlocks the Review tab. Set to 0 or below to disable (admin-promoted moderators only).
    "MODERATOR_REPUTATION": env_int("MODERATOR_REPUTATION", 100),
    # Contributors below this are flagged "low_reputation" in the queue (stricter review).
    "LOW_REPUTATION": env_int("LOW_REPUTATION", 0),
    "PREDICTION_RADIUS_KM": env_int("PREDICTION_RADIUS_KM", 50),
    "BLOOMING_SOON_DAYS": env_int("BLOOMING_SOON_DAYS", 30),
    "MAP_PIN_LIMIT": env_int("MAP_PIN_LIMIT", 500),
    "DUPLICATE_RADIUS_M": env_int("DUPLICATE_RADIUS_M", 100),
}

# --- Photo storage ----------------------------------------------------------
# PHOTO_STORAGE=local -> files saved under MEDIA_ROOT and served by Django (local dev only;
#                        Render's disk is wiped on restart).
# PHOTO_STORAGE=s3    -> any S3-compatible bucket (Cloudflare R2, Supabase Storage, AWS S3).

PHOTO_STORAGE = os.environ.get("PHOTO_STORAGE", "local")
PHOTO_MAX_BYTES = env_int("PHOTO_MAX_BYTES", 10 * 1024 * 1024)
PHOTO_UPLOAD_EXPIRES = env_int("PHOTO_UPLOAD_EXPIRES", 300)
PHOTO_ALLOWED_TYPES = {"image/jpeg": "jpg", "image/png": "png", "image/heic": "heic"}

S3_ENDPOINT_URL = os.environ.get("S3_ENDPOINT_URL")          # e.g. https://<account>.r2.cloudflarestorage.com
S3_REGION = os.environ.get("S3_REGION", "auto")
S3_BUCKET = os.environ.get("S3_BUCKET", "")
S3_ACCESS_KEY_ID = os.environ.get("S3_ACCESS_KEY_ID", "")
S3_SECRET_ACCESS_KEY = os.environ.get("S3_SECRET_ACCESS_KEY", "")
# If the bucket is public, photo URLs are <base>/<key>. Otherwise signed GET URLs are generated.
PHOTO_PUBLIC_BASE_URL = os.environ.get("PHOTO_PUBLIC_BASE_URL", "").rstrip("/")
PHOTO_URL_EXPIRES = env_int("PHOTO_URL_EXPIRES", 3600)

# --- Logging ----------------------------------------------------------------

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": os.environ.get("LOG_LEVEL", "INFO")},
}
