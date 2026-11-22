from django.conf import settings
from django.contrib import admin
from django.db import connection
from django.http import JsonResponse
from django.urls import include, path, re_path
from django.views.static import serve
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from plants.views import CalendarView
from submissions.views import SubmissionCreateView

admin.site.site_header = "Bloom admin"
admin.site.site_title = "Bloom admin"


def health(request):
    """Render pings this to check the service is up. Kept DB-free so it stays fast."""
    return JsonResponse({"status": "ok"})


def db_check(request):
    """Manual check that Django can reach the database and PostGIS is enabled."""
    with connection.cursor() as cur:
        cur.execute("SELECT version(), postgis_version()")
        pg, postgis = cur.fetchone()
    return JsonResponse({"postgres": pg, "postgis": postgis})


# API paths have NO trailing slash; core.middleware.ApiTrailingSlashMiddleware also accepts one.
api_v1 = [
    path("auth/", include("users.urls_auth")),
    path("users/", include("users.urls")),
    path("plants/", include("plants.urls")),
    path("map/", include("submissions.urls_map")),
    path("calendar", CalendarView.as_view(), name="calendar"),
    path("uploads/", include("submissions.urls_uploads")),
    path("submissions", SubmissionCreateView.as_view(), name="submissions-create"),
    path("submissions/", include("submissions.urls")),
    path("moderation/", include("moderation.urls")),
]

urlpatterns = [
    path("admin/", admin.site.urls),
    path("health/", health),
    path("health/db/", db_check),
    path("api/v1/", include(api_v1)),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="docs"),
]

if settings.PHOTO_STORAGE == "local":
    # Dev only: serve uploaded photos from MEDIA_ROOT. In production photos come from the bucket.
    urlpatterns += [re_path(r"^media/(?P<path>.*)$", serve, {"document_root": settings.MEDIA_ROOT})]
