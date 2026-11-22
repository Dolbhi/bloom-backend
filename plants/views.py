from django.conf import settings
from django.contrib.postgres.search import TrigramWordSimilarity
from django.db.models import Case, IntegerField, Q, Value, When
from django.db.models.functions import Coalesce, Greatest
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core import bloom, params
from core.choices import ModerationStatus, PlantStatus
from core.serializers import paginate_nested
from core.storage import photo_url
from submissions.serializers import GallerySubmissionSerializer

from .models import Plant
from .prediction import predict_for_plant, predict_nearby, public
from .serializers import PlantEditCreateSerializer, PlantSearchSerializer

SEARCH_LIMIT = 10
MIN_SIMILARITY = 0.3
LOCATIONS_LIMIT = 500

LAT_LNG_PARAMS = [
    OpenApiParameter("lat", OpenApiTypes.NUMBER, description="User latitude (optional, for local prediction)"),
    OpenApiParameter("lng", OpenApiTypes.NUMBER, description="User longitude"),
]


class PlantSearchView(APIView):
    """Autocomplete (F3). Fuzzy: 'wattel' still finds 'Wattle'."""

    permission_classes = [AllowAny]

    @extend_schema(
        parameters=[OpenApiParameter("q", OpenApiTypes.STR, required=True, description="At least 2 characters")],
        responses=PlantSearchSerializer(many=True),
        tags=["plants"],
    )
    def get(self, request):
        q = (request.query_params.get("q") or "").strip()
        if len(q) < 2:
            raise ValidationError({"q": ["Type at least 2 characters."]})

        visible = Q(status=PlantStatus.APPROVED)
        if request.user.is_authenticated:
            visible |= Q(status=PlantStatus.PENDING, created_by=request.user)   # your own new plants too

        plants = (
            Plant.objects.filter(visible)
            .annotate(
                similarity=Greatest(
                    TrigramWordSimilarity(q, "common_name"),
                    TrigramWordSimilarity(q, Coalesce("scientific_name", Value(""))),
                ),
                approved_first=Case(When(status=PlantStatus.APPROVED, then=0), default=1, output_field=IntegerField()),
            )
            .filter(Q(common_name__icontains=q) | Q(scientific_name__icontains=q) | Q(similarity__gte=MIN_SIMILARITY))
            .order_by("approved_first", "-similarity", "common_name")[:SEARCH_LIMIT]
        )
        return Response(PlantSearchSerializer(plants, many=True).data)


class PlantDetailView(APIView):
    """Everything the Plant Details screen needs, in one request (F4)."""

    permission_classes = [AllowAny]

    @extend_schema(parameters=LAT_LNG_PARAMS, responses=OpenApiTypes.OBJECT, tags=["plants"])
    def get(self, request, pk):
        plant = get_object_or_404(Plant.objects.select_related("hero_submission"), pk=pk)
        if not plant.visible_to(request.user):
            raise Http404
        lat, lng = params.lat_lng(request.query_params)

        approved = plant.submissions.filter(status=ModerationStatus.APPROVED)
        hero = plant.hero_submission
        if hero is None or hero.status != ModerationStatus.APPROVED:
            hero = approved.order_by("created_at").first()

        locations = [
            {"submission_id": s.id, "lat": s.lat, "lng": s.lng}
            for s in approved.only("id", "location").order_by("-created_at")[:LOCATIONS_LIMIT]
        ]
        gallery = approved.select_related("user", "plant").order_by("-created_at")

        return Response({
            "id": plant.id,
            "common_name": plant.common_name,
            "scientific_name": plant.scientific_name,
            "description": plant.description,
            "status": plant.status,
            "hero_photo_url": photo_url(hero.photo_key, request) if hero else None,
            "prediction": public(predict_for_plant(plant.id, lat, lng)),
            "locations": locations,
            "submissions": paginate_nested(request, gallery, GallerySubmissionSerializer, {"request": request}),
        })


class PlantEditCreateView(APIView):
    """Suggest an edit to a plant (F12). Goes into the moderation queue."""

    permission_classes = [IsAuthenticated]

    @extend_schema(request=PlantEditCreateSerializer, responses={201: PlantEditCreateSerializer}, tags=["plants"])
    def post(self, request, pk):
        plant = get_object_or_404(Plant, pk=pk)
        if not plant.visible_to(request.user):
            raise Http404
        serializer = PlantEditCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(plant=plant, user=request.user)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class CalendarView(APIView):
    """Blooming now / soon / season timeline near the user (F9, UF8)."""

    permission_classes = [AllowAny]

    @extend_schema(
        parameters=[
            OpenApiParameter("lat", OpenApiTypes.NUMBER, required=True),
            OpenApiParameter("lng", OpenApiTypes.NUMBER, required=True),
            OpenApiParameter("season", OpenApiTypes.STR, enum=list(bloom.SEASONS),
                             description="Defaults to the current season at this latitude"),
        ],
        responses=OpenApiTypes.OBJECT,
        tags=["calendar"],
    )
    def get(self, request):
        lat, lng = params.lat_lng(request.query_params, required=True)
        today = timezone.localdate()
        season = params.choice(request.query_params, "season", bloom.SEASONS) or bloom.current_season(lat, today)
        season_start, season_end = bloom.season_doy_range(season, lat)

        now, soon, timeline = [], [], []
        for plant_id, name, pred in predict_nearby(lat, lng, today):
            item = {"plant_id": plant_id, "common_name": name, "start": pred["start"], "end": pred["end"],
                    "based_on": pred["based_on"]}
            if pred["bloom_status"] == bloom.BLOOMING_NOW:
                now.append(item)
            elif pred["bloom_status"] == bloom.BLOOMING_SOON:
                soon.append({**item, "starts_in_days": pred["starts_in_days"]})
            if bloom.windows_overlap(pred["_start_doy"], pred["_end_doy"], season_start, season_end):
                timeline.append((pred["_start_doy"], item))

        soon.sort(key=lambda i: i["starts_in_days"])
        # Timeline ordered from the start of the season, so a window starting before it comes first
        timeline.sort(key=lambda t: bloom.days_until(season_start, t[0]) if bloom.in_window(t[0], season_start, season_end) else -1)

        return Response({
            "hemisphere": bloom.hemisphere(lat),
            "season": season,
            "months": [f"{m:02d}" for m in bloom.season_months(season, lat)],
            "radius_km": settings.BLOOM["PREDICTION_RADIUS_KM"],
            "blooming_now": now,
            "blooming_soon": soon,
            "timeline": [item for _, item in timeline],
        })
