"""Possible duplicates (F13): same plant, close by, overlapping bloom dates. ⚠️ Thresholds are guesses."""
from django.conf import settings
from django.contrib.gis.db.models.functions import Distance
from django.contrib.gis.measure import D

from core.choices import ModerationStatus

from .models import Submission


def possible_duplicates(submission, limit=10):
    qs = (
        Submission.objects.filter(
            plant_id=submission.plant_id,
            location__dwithin=(submission.location, D(m=settings.BLOOM["DUPLICATE_RADIUS_M"])),
            bloom_start__lte=submission.bloom_end,
            bloom_end__gte=submission.bloom_start,
        )
        .exclude(pk=submission.pk)
        .exclude(status=ModerationStatus.REJECTED)
        .annotate(distance=Distance("location", submission.location))
        .order_by("distance")[:limit]
    )
    return [{"id": s.id, "metres_away": round(s.distance.m), "status": s.status} for s in qs]
