from django.conf import settings
from django.db import models
from django.db.models import Q

from core.choices import Decision


class Review(models.Model):
    """One moderator decision. History: never edited, so no updated_at."""

    reviewer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.RESTRICT, related_name="reviews_written")
    submission = models.ForeignKey(
        "submissions.Submission", null=True, blank=True, on_delete=models.CASCADE, related_name="reviews"
    )
    submission_revision = models.PositiveIntegerField(null=True, blank=True)
    plant_edit = models.ForeignKey(
        "plants.PlantEdit", null=True, blank=True, on_delete=models.CASCADE, related_name="reviews"
    )
    decision = models.CharField(max_length=20, choices=Decision.choices)
    comment = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            # Exactly one target: a submission OR a plant edit
            models.CheckConstraint(
                condition=(Q(submission__isnull=False) & Q(plant_edit__isnull=True))
                | (Q(submission__isnull=True) & Q(plant_edit__isnull=False)),
                name="review_exactly_one_target",
            ),
            models.CheckConstraint(
                condition=Q(submission__isnull=True) | Q(submission_revision__isnull=False),
                name="review_revision_with_submission",
            ),
            models.CheckConstraint(condition=Q(decision__in=Decision.values), name="review_decision_valid"),
            models.CheckConstraint(
                condition=~Q(decision="request_changes") | ~Q(comment=""),
                name="review_comment_for_changes",
            ),
            # One decision per version of a submission
            models.UniqueConstraint(
                fields=["submission", "submission_revision"],
                condition=Q(submission__isnull=False),
                name="review_one_per_revision",
            ),
        ]

    def __str__(self):
        target = f"submission #{self.submission_id}" if self.submission_id else f"plant edit #{self.plant_edit_id}"
        return f"{self.decision} on {target}"


class ReputationReason(models.TextChoices):
    SUBMISSION_APPROVED = "submission_approved"
    SUBMISSION_REJECTED = "submission_rejected"
    EDIT_APPROVED = "edit_approved"
    EDIT_REJECTED = "edit_rejected"
    REVIEW_COMPLETED = "review_completed"
    ADMIN_ADJUSTMENT = "admin_adjustment"


class ReputationEvent(models.Model):
    """Every change to a user's score. user.reputation is the cached SUM(delta) of these rows."""

    Reason = ReputationReason

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="reputation_events")
    delta = models.IntegerField()
    reason = models.CharField(max_length=30, choices=Reason.choices)
    review = models.ForeignKey(Review, null=True, blank=True, on_delete=models.SET_NULL, related_name="reputation_events")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(condition=~Q(delta=0), name="reputation_delta_not_zero"),
            models.CheckConstraint(condition=Q(reason__in=ReputationReason.values), name="reputation_reason_valid"),
        ]

    def __str__(self):
        return f"{self.delta:+d} {self.reason} for {self.user}"
