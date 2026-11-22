from django.shortcuts import get_object_or_404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from core import params
from core.choices import ModerationStatus
from core.permissions import IsModerator
from core.storage import photo_url
from plants.models import PlantEdit
from submissions.duplicates import possible_duplicates
from submissions.models import Submission

from . import services
from .models import Review
from .serializers import DecisionSerializer, ReviewHistorySerializer, contributor_block

QUEUE_TYPES = ("submission", "plant_edit")


class QueueView(APIView):
    """Pending submissions + plant edits, oldest first. Your own items are left out."""

    permission_classes = [IsModerator]

    @extend_schema(
        parameters=[OpenApiParameter("type", OpenApiTypes.STR, enum=list(QUEUE_TYPES)),
                    OpenApiParameter("page", OpenApiTypes.INT)],
        responses=OpenApiTypes.OBJECT,
        tags=["moderation"],
    )
    def get(self, request):
        kind = params.choice(request.query_params, "type", QUEUE_TYPES)
        items = []

        if kind in (None, "submission"):
            subs = (
                Submission.objects.filter(status=ModerationStatus.PENDING)
                .exclude(user=request.user)
                .select_related("plant", "user")
            )
            items += [
                {
                    "type": "submission",
                    "id": s.id,
                    "thumbnail_url": photo_url(s.photo_key, request),
                    "plant_name": s.plant.common_name,
                    "plant_status": s.plant.status,
                    "revision": s.revision,
                    "contributor": contributor_block(s.user),
                    "created_at": s.created_at,
                    "queued_at": s.updated_at,   # resubmissions re-enter the queue at their resubmit time
                }
                for s in subs
            ]

        if kind in (None, "plant_edit"):
            edits = (
                PlantEdit.objects.filter(status=ModerationStatus.PENDING)
                .exclude(user=request.user)
                .select_related("plant", "user")
            )
            items += [
                {
                    "type": "plant_edit",
                    "id": e.id,
                    "plant": {"id": e.plant_id, "common_name": e.plant.common_name},
                    "proposed_changes": e.proposed_changes,
                    "contributor": contributor_block(e.user),
                    "created_at": e.created_at,
                    "queued_at": e.updated_at,
                }
                for e in edits
            ]

        items.sort(key=lambda i: i["queued_at"])
        paginator = PageNumberPagination()
        page = paginator.paginate_queryset(items, request, view=self)
        return paginator.get_paginated_response(page)


def _decision_response(item_key, item_id, result):
    return {
        item_key: {"id": item_id, "status": result.status},
        "review": {
            "id": result.review.id,
            "decision": result.review.decision,
            "comment": result.review.comment,
            "submission_revision": result.review.submission_revision,
        },
        "reputation_changes": result.reputation_changes,
    }


class SubmissionReviewView(APIView):
    permission_classes = [IsModerator]

    @extend_schema(responses=OpenApiTypes.OBJECT, tags=["moderation"])
    def get(self, request, pk):
        s = get_object_or_404(Submission.objects.select_related("plant", "user"), pk=pk)
        history = Review.objects.filter(submission=s).select_related("reviewer").order_by("-created_at")
        return Response({
            "id": s.id,
            "status": s.status,
            "revision": s.revision,
            "photo_url": photo_url(s.photo_key, request),
            "plant": {"id": s.plant_id, "common_name": s.plant.common_name, "status": s.plant.status,
                      "scientific_name": s.plant.scientific_name},
            "lat": s.lat,
            "lng": s.lng,
            "bloom_start": s.bloom_start,
            "bloom_end": s.bloom_end,
            "description": s.description,
            "contributor": contributor_block(s.user),
            "is_own": s.user_id == request.user.id,
            "possible_duplicates": possible_duplicates(s),
            "previous_reviews": ReviewHistorySerializer(history, many=True).data,
            "created_at": s.created_at,
            "updated_at": s.updated_at,
        })


class SubmissionDecisionView(APIView):
    permission_classes = [IsModerator]

    @extend_schema(request=DecisionSerializer, responses=OpenApiTypes.OBJECT, tags=["moderation"])
    def post(self, request, pk):
        submission = get_object_or_404(Submission, pk=pk)
        serializer = DecisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = services.decide_submission(submission.pk, request.user, **serializer.validated_data)
        return Response(_decision_response("submission", submission.pk, result))


class PlantEditReviewView(APIView):
    permission_classes = [IsModerator]

    @extend_schema(responses=OpenApiTypes.OBJECT, tags=["moderation"])
    def get(self, request, pk):
        e = get_object_or_404(PlantEdit.objects.select_related("plant", "user"), pk=pk)
        plant = e.plant
        history = Review.objects.filter(plant_edit=e).select_related("reviewer").order_by("-created_at")
        return Response({
            "id": e.id,
            "status": e.status,
            "plant": {"id": plant.id, "common_name": plant.common_name, "status": plant.status},
            # Current values next to proposed ones, so the moderator can compare
            "current": {k: getattr(plant, k) for k in e.proposed_changes},
            "proposed_changes": e.proposed_changes,
            "reason": e.reason,
            "contributor": contributor_block(e.user),
            "is_own": e.user_id == request.user.id,
            "previous_reviews": ReviewHistorySerializer(history, many=True).data,
            "created_at": e.created_at,
        })


class PlantEditDecisionView(APIView):
    permission_classes = [IsModerator]

    @extend_schema(request=DecisionSerializer, responses=OpenApiTypes.OBJECT, tags=["moderation"])
    def post(self, request, pk):
        edit = get_object_or_404(PlantEdit, pk=pk)
        serializer = DecisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = services.decide_plant_edit(edit.pk, request.user, **serializer.validated_data)
        return Response(_decision_response("plant_edit", edit.pk, result))
