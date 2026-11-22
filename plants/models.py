from django.conf import settings
from django.contrib.postgres.indexes import GinIndex
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower

from core.choices import ModerationStatus, PlantStatus

# Fields a plant edit (F12) is allowed to change
EDITABLE_PLANT_FIELDS = ("common_name", "scientific_name", "description")


class Plant(models.Model):
    """One species page. Groups many submissions (sightings)."""

    common_name = models.CharField(max_length=120)          # not unique: several plants share common names
    scientific_name = models.CharField(max_length=200, null=True, blank=True)
    description = models.TextField(blank=True, default="")
    status = models.CharField(max_length=10, choices=PlantStatus.choices, default=PlantStatus.APPROVED)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="plants_created"
    )
    hero_submission = models.ForeignKey(
        "submissions.Submission", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["common_name"]
        constraints = [
            models.UniqueConstraint(
                Lower("scientific_name"),
                condition=Q(scientific_name__isnull=False) & ~Q(scientific_name=""),
                name="plant_scientific_name_lower_uq",
            ),
            models.CheckConstraint(condition=Q(status__in=PlantStatus.values), name="plant_status_valid"),
        ]
        indexes = [
            # Trigram indexes for fuzzy autocomplete (needs the pg_trgm extension, added in migration 0001)
            GinIndex(fields=["common_name"], opclasses=["gin_trgm_ops"], name="plant_common_trgm"),
            GinIndex(fields=["scientific_name"], opclasses=["gin_trgm_ops"], name="plant_scientific_trgm"),
        ]

    def __str__(self):
        return self.common_name

    def clean(self):
        if self.scientific_name == "":
            self.scientific_name = None
        hero = self.hero_submission
        if hero is not None and (hero.plant_id != self.pk or hero.status != ModerationStatus.APPROVED):
            raise ValidationError({"hero_submission": "Hero photo must be an approved sighting of this plant."})

    def save(self, *args, **kwargs):
        if self.scientific_name is not None:
            self.scientific_name = self.scientific_name.strip() or None
        super().save(*args, **kwargs)

    def visible_to(self, user):
        if self.status == PlantStatus.APPROVED:
            return True
        return bool(user and user.is_authenticated and (user.can_moderate or self.created_by_id == user.id))


class PlantEdit(models.Model):
    """A "Suggest edit" request on a plant (F12). Goes through moderation like a submission."""

    plant = models.ForeignKey(Plant, on_delete=models.CASCADE, related_name="edits")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="plant_edits")
    proposed_changes = models.JSONField()
    reason = models.TextField(blank=True, default="")
    status = models.CharField(max_length=20, choices=ModerationStatus.choices, default=ModerationStatus.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(status__in=ModerationStatus.values), name="plant_edit_status_valid"),
            models.CheckConstraint(condition=~Q(proposed_changes={}), name="plant_edit_changes_not_empty"),
        ]
        indexes = [
            models.Index(fields=["created_at"], condition=Q(status="pending"), name="plant_edit_pending_idx"),
        ]

    def __str__(self):
        return f"Edit #{self.pk} on {self.plant}"
