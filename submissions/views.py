import os
import tempfile

from django.conf import settings
from django.contrib.gis.geos import Polygon
from django.contrib.gis.measure import D
from django.core import signing
from django.db import transaction
from django.http import Http404, HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core import bloom, params
from core.choices import ModerationStatus, PlantStatus
from core.exceptions import Conflict
from core.storage import LocalStorage, get_storage, new_photo_key, photo_url

from .models import Submission
from .serializers import (
    PresignRequestSerializer,
    PresignResponseSerializer,
    SubmissionCreatedSerializer,
    SubmissionDetailSerializer,
    SubmissionWriteSerializer,
    with_latest_review,
)


# --- Uploads (F5) -----------------------------------------------------------

class PresignView(APIView):
    """Step 1 of submitting: get a short-lived URL, then PUT the photo bytes straight to it."""

    permission_classes = [IsAuthenticated]

    @extend_schema(request=PresignRequestSerializer, responses=PresignResponseSerializer, tags=["submissions"])
    def post(self, request):
        serializer = PresignRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        content_type = serializer.validated_data["content_type"]
        key = new_photo_key(request.user.id, content_type)
        return Response({
            "upload_url": get_storage().presign_upload(key, content_type, request),
            "photo_key": key,
            "expires_in": settings.PHOTO_UPLOAD_EXPIRES,
            "method": "PUT",
            "headers": {"Content-Type": content_type},
        })


@csrf_exempt
def local_upload(request, token):
    """Dev-only stand-in for S3: accepts the PUT from a 'local' upload URL and saves the file."""
    storage = get_storage()
    if not isinstance(storage, LocalStorage):
        raise Http404
    if request.method != "PUT":
        return HttpResponse(status=405, headers={"Allow": "PUT"})
    try:
        key, content_type = storage.read_upload_token(token)
    except signing.SignatureExpired:
        return JsonResponse({"detail": "Upload URL expired."}, status=403)
    except signing.BadSignature:
        return JsonResponse({"detail": "Invalid upload URL."}, status=403)
    if (request.content_type or "") != content_type:
        return HttpResponseBadRequest(f"Content-Type must be {content_type}")

    path = storage.path_for(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    fd, tmp = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as out:
            # Read in chunks (not request.body) so big files don't sit in memory
            while chunk := request.read(64 * 1024):
                written += len(chunk)
                if written > settings.PHOTO_MAX_BYTES:
                    raise ValueError
                out.write(chunk)
        if written == 0:
            raise ValueError
        os.replace(tmp, path)
    except ValueError:
        os.unlink(tmp)
        return HttpResponseBadRequest("File empty or over the size limit.")
    return HttpResponse(status=200)


# --- Submissions (F6, F11) --------------------------------------------------

class SubmissionCreateView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=SubmissionWriteSerializer, responses={201: SubmissionCreatedSerializer}, tags=["submissions"])
    def post(self, request):
        serializer = SubmissionWriteSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        submission = serializer.save()
        return Response(SubmissionCreatedSerializer(submission).data, status=status.HTTP_201_CREATED)


class SubmissionDetailView(APIView):
    def get_permissions(self):
        return [AllowAny()] if self.request.method == "GET" else [IsAuthenticated()]

    @extend_schema(responses=SubmissionDetailSerializer, tags=["submissions"])
    def get(self, request, pk):
        submission = get_object_or_404(
            with_latest_review(Submission.objects.select_related("plant", "user")), pk=pk
        )
        if not submission.visible_to(request.user):
            raise Http404
        return Response(SubmissionDetailSerializer(submission, context={"request": request}).data)

    @extend_schema(request=SubmissionWriteSerializer, responses=SubmissionDetailSerializer, tags=["submissions"])
    def patch(self, request, pk):
        """Edit and resubmit: owner only, only while status is changes_requested."""
        with transaction.atomic():
            submission = get_object_or_404(Submission.objects.select_for_update(), pk=pk)
            if submission.user_id != request.user.id:
                if not submission.visible_to(request.user):
                    raise Http404
                raise PermissionDenied("Only the owner can edit this submission.")
            if submission.status != ModerationStatus.CHANGES_REQUESTED:
                raise Conflict("Only submissions with changes requested can be edited.")
            serializer = SubmissionWriteSerializer(
                submission, data=request.data, partial=True, context={"request": request}
            )
            serializer.is_valid(raise_exception=True)
            serializer.save()

        submission = with_latest_review(Submission.objects.select_related("plant", "user")).get(pk=pk)
        return Response(SubmissionDetailSerializer(submission, context={"request": request}).data)


# --- Map (F2) ---------------------------------------------------------------

class MapPinsView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(
        parameters=[
            OpenApiParameter("bbox", OpenApiTypes.STR, required=True, description="minLng,minLat,maxLng,maxLat"),
            OpenApiParameter("plant", OpenApiTypes.INT),
            OpenApiParameter("blooming_now", OpenApiTypes.BOOL),
            OpenApiParameter("season", OpenApiTypes.STR, enum=list(bloom.SEASONS)),
            OpenApiParameter("near", OpenApiTypes.STR, description="lat,lng (use with radius_km)"),
            OpenApiParameter("radius_km", OpenApiTypes.NUMBER),
        ],
        responses=OpenApiTypes.OBJECT,
        tags=["map"],
    )
    def get(self, request):
        qp = request.query_params
        min_lng, min_lat, max_lng, max_lat = params.bbox(qp)
        box = Polygon.from_bbox((min_lng, min_lat, max_lng, max_lat))
        box.srid = 4326

        qs = Submission.objects.filter(
            status=ModerationStatus.APPROVED,
            plant__status=PlantStatus.APPROVED,
            location__intersects=box,
        )
        plant_id = params.positive_int(qp, "plant")
        if plant_id:
            qs = qs.filter(plant_id=plant_id)

        today = timezone.localdate()
        blooming_now = params.boolean(qp, "blooming_now")
        season = params.choice(qp, "season", bloom.SEASONS)
        if blooming_now is not None or season:
            qs = bloom.annotate_window(qs)
            if blooming_now is True:
                qs = qs.filter(bloom.md_in_window_q(bloom.md(today)))
            elif blooming_now is False:
                qs = qs.exclude(bloom.md_in_window_q(bloom.md(today)))
            if season:
                centre_lat = (min_lat + max_lat) / 2
                qs = qs.filter(bloom.window_overlaps_md_range_q(*bloom.season_md_range(season, centre_lat)))

        near = params.near(qp)
        if near:
            qs = qs.filter(location__dwithin=(near[0], D(km=near[1])))

        limit = settings.BLOOM["MAP_PIN_LIMIT"]
        rows = list(qs.select_related("plant").order_by("-created_at")[: limit + 1])
        truncated = len(rows) > limit
        rows = rows[:limit]
        soon = settings.BLOOM["BLOOMING_SOON_DAYS"]

        results = [
            {
                "id": s.id,
                "lat": s.lat,
                "lng": s.lng,
                "plant": {"id": s.plant_id, "common_name": s.plant.common_name},
                "bloom_start": s.bloom_start,
                "bloom_end": s.bloom_end,
                "bloom_status": bloom.dates_status(s.bloom_start, s.bloom_end, today, soon)[0],
                "thumbnail_url": photo_url(s.photo_key, request),
            }
            for s in rows
        ]
        return Response({"count": len(results), "truncated": truncated, "results": results})
