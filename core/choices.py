from django.db import models


class ModerationStatus(models.TextChoices):
    """Status shared by submissions and plant edits."""

    PENDING = "pending"
    APPROVED = "approved"
    CHANGES_REQUESTED = "changes_requested"
    REJECTED = "rejected"


class PlantStatus(models.TextChoices):
    PENDING = "pending"
    APPROVED = "approved"


class Decision(models.TextChoices):
    APPROVE = "approve"
    REQUEST_CHANGES = "request_changes"
    REJECT = "reject"


# What each moderator decision does to the item's status
DECISION_TO_STATUS = {
    Decision.APPROVE: ModerationStatus.APPROVED,
    Decision.REQUEST_CHANGES: ModerationStatus.CHANGES_REQUESTED,
    Decision.REJECT: ModerationStatus.REJECTED,
}
