"""
Moderation decisions (UF6, UF7) and reputation (F8).

Each decision is ONE database transaction: status change + review row + reputation,
all or nothing. The status update has `WHERE status='pending'`, so if two moderators press
a button at the same moment, the second one updates 0 rows and gets a 409 instead of
double-counting reputation.

Used by the API views AND the Django Admin actions, so both follow the same rules.
"""
from dataclasses import dataclass, field

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import F, Sum
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from core.choices import DECISION_TO_STATUS, Decision, ModerationStatus, PlantStatus
from core.exceptions import Conflict
from plants.models import EDITABLE_PLANT_FIELDS, Plant, PlantEdit
from submissions.models import Submission

from .models import ReputationEvent, Review

Reason = ReputationEvent.Reason


@dataclass
class DecisionResult:
    review: Review
    status: str
    reputation_changes: list = field(default_factory=list)


def add_reputation(user_id, delta, reason, review=None):
    """Log the event and update the cached total. Call inside a transaction."""
    if not delta:
        return None
    event = ReputationEvent.objects.create(user_id=user_id, delta=delta, reason=reason, review=review)
    get_user_model().objects.filter(pk=user_id).update(reputation=F("reputation") + delta)
    return {"user_id": user_id, "delta": delta, "reason": reason}


def rebuild_reputation():
    """Recalculate every user's score from reputation_event rows. Returns number of users changed."""
    User = get_user_model()
    totals = dict(ReputationEvent.objects.values_list("user").annotate(total=Sum("delta")))
    changed = 0
    with transaction.atomic():
        for user in User.objects.only("id", "reputation"):
            correct = totals.get(user.id, 0)
            if user.reputation != correct:
                User.objects.filter(pk=user.id).update(reputation=correct)
                changed += 1
    return changed


def _check(decision, comment, reviewer, author_id):
    if decision not in Decision.values:
        raise ValidationError({"decision": [f"Must be one of: {', '.join(Decision.values)}."]})
    if decision == Decision.REQUEST_CHANGES and not (comment or "").strip():
        raise ValidationError({"comment": ["A comment is required when requesting changes."]})
    if not reviewer.can_moderate:
        raise PermissionDenied("Only moderators can do this.")
    if author_id == reviewer.id:
        raise PermissionDenied("You cannot review your own submission.")


def decide_submission(submission_id, reviewer, decision, comment=""):
    submission = Submission.objects.select_related("plant").get(pk=submission_id)
    _check(decision, comment, reviewer, submission.user_id)
    new_status = DECISION_TO_STATUS[decision]
    rules = settings.BLOOM

    with transaction.atomic():
        updated = Submission.objects.filter(pk=submission.pk, status=ModerationStatus.PENDING).update(
            status=new_status, updated_at=timezone.now()
        )
        if not updated:
            raise Conflict("This submission has already been decided.")

        review = Review.objects.create(
            reviewer=reviewer,
            submission=submission,
            submission_revision=submission.revision,
            decision=decision,
            comment=(comment or "").strip(),
        )

        if decision == Decision.APPROVE:
            plant = Plant.objects.select_for_update().get(pk=submission.plant_id)
            fields = []
            if plant.status == PlantStatus.PENDING:   # first approved sighting makes a new plant public
                plant.status = PlantStatus.APPROVED
                fields.append("status")
            if plant.hero_submission_id is None:      # first approved photo becomes the hero photo
                plant.hero_submission_id = submission.pk
                fields.append("hero_submission")
            if fields:
                plant.save(update_fields=fields + ["updated_at"])

        author_delta = {
            Decision.APPROVE: (rules["REP_SUBMISSION_APPROVED"], Reason.SUBMISSION_APPROVED),
            Decision.REJECT: (rules["REP_SUBMISSION_REJECTED"], Reason.SUBMISSION_REJECTED),
        }.get(decision)

        changes = []
        if author_delta:
            changes.append(add_reputation(submission.user_id, *author_delta, review=review))
        changes.append(add_reputation(reviewer.id, rules["REP_REVIEW_COMPLETED"], Reason.REVIEW_COMPLETED, review))

    return DecisionResult(review=review, status=new_status, reputation_changes=[c for c in changes if c])


def decide_plant_edit(edit_id, reviewer, decision, comment=""):
    edit = PlantEdit.objects.get(pk=edit_id)
    _check(decision, comment, reviewer, edit.user_id)
    new_status = DECISION_TO_STATUS[decision]
    rules = settings.BLOOM

    with transaction.atomic():
        updated = PlantEdit.objects.filter(pk=edit.pk, status=ModerationStatus.PENDING).update(
            status=new_status, updated_at=timezone.now()
        )
        if not updated:
            raise Conflict("This plant edit has already been decided.")

        if decision == Decision.APPROVE:
            plant = Plant.objects.select_for_update().get(pk=edit.plant_id)
            changes = {k: v for k, v in edit.proposed_changes.items() if k in EDITABLE_PLANT_FIELDS}
            new_sci = changes.get("scientific_name")
            if new_sci and Plant.objects.filter(scientific_name__iexact=new_sci.strip()).exclude(pk=plant.pk).exists():
                raise Conflict("Another plant already uses this scientific name.")
            for key, value in changes.items():
                setattr(plant, key, value)
            plant.save()

        review = Review.objects.create(
            reviewer=reviewer, plant_edit=edit, decision=decision, comment=(comment or "").strip()
        )

        author_delta = {
            Decision.APPROVE: (rules["REP_EDIT_APPROVED"], Reason.EDIT_APPROVED),
            Decision.REJECT: (rules["REP_EDIT_REJECTED"], Reason.EDIT_REJECTED),
        }.get(decision)

        rep = []
        if author_delta:
            rep.append(add_reputation(edit.user_id, *author_delta, review=review))
        rep.append(add_reputation(reviewer.id, rules["REP_REVIEW_COMPLETED"], Reason.REVIEW_COMPLETED, review))

    return DecisionResult(review=review, status=new_status, reputation_changes=[c for c in rep if c])
