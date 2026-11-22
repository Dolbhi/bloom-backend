from django.conf import settings
from django.contrib.gis.db import models as gis
from django.db import models
from django.db.models import F, Q

from core.choices import ModerationStatus
from core.permissions import is_moderator

MAX_WINDOW_DAYS = 366


class Submission(models.Model):
    """One sighting: photo + place + bloom window. Nothing is public until approved."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="submissions")
    plant = models.ForeignKey("plants.Plant", on_delete=models.RESTRICT, related_name="submissions")
    # ⚠️ Longitude first: Point(lng, lat). geography=True -> distances in metres.
    # GeoDjango adds a GiST spatial index automatically (spatial_index=True by default).
    location = gis.PointField(geography=True, srid=4326)
    bloom_start = models.DateField()
    bloom_end = models.DateField()
    description = models.TextField(blank=True, default="")
    photo_key = models.CharField(max_length=255)
    status = models.CharField(max_length=20, choices=ModerationStatus.choices, default=ModerationStatus.PENDING)
    revision = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(bloom_end__gte=F("bloom_start")), name="bloom_window_order"),
            models.CheckConstraint(condition=Q(status__in=ModerationStatus.values), name="submission_status_valid"),
            models.CheckConstraint(condition=Q(revision__gte=1), name="submission_revision_positive"),
        ]
        indexes = [
            models.Index(fields=["plant"], condition=Q(status="approved"), name="submission_plant_approved_idx"),
            models.Index(fields=["created_at"], condition=Q(status="pending"), name="submission_pending_idx"),
            models.Index(fields=["user", "-created_at"], name="submission_user_idx"),
        ]

    def __str__(self):
        return f"#{self.pk} {self.plant} ({self.status})"

    @property
    def lat(self):
        return self.location.y

    @property
    def lng(self):
        return self.location.x

    def visible_to(self, user):
        """Approved = public. Anything else = owner or moderator only (others get 404)."""
        if self.status == ModerationStatus.APPROVED:
            return True
        return bool(user and user.is_authenticated and (self.user_id == user.id or is_moderator(user)))
