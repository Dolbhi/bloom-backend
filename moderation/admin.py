from django.contrib import admin
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import F

from .models import ReputationEvent, Review


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    """Read-only history. Decisions are made via the API or the Submission admin actions."""

    list_display = ("id", "decision", "submission", "submission_revision", "plant_edit", "reviewer", "created_at")
    list_filter = ("decision",)
    list_select_related = ("reviewer",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(ReputationEvent)
class ReputationEventAdmin(admin.ModelAdmin):
    """Add an event here to adjust someone's score by hand (reason: admin_adjustment)."""

    list_display = ("id", "user", "delta", "reason", "review", "created_at")
    list_filter = ("reason",)
    raw_id_fields = ("user", "review")

    def get_changeform_initial_data(self, request):
        return {"reason": ReputationEvent.Reason.ADMIN_ADJUSTMENT}

    def has_change_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        with transaction.atomic():
            super().save_model(request, obj, form, change)
            get_user_model().objects.filter(pk=obj.user_id).update(reputation=F("reputation") + obj.delta)
