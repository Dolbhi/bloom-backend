from django.contrib import admin, messages
from rest_framework.exceptions import APIException

from core.choices import Decision
from moderation.services import decide_plant_edit

from .models import Plant, PlantEdit


@admin.register(Plant)
class PlantAdmin(admin.ModelAdmin):
    list_display = ("id", "common_name", "scientific_name", "status", "created_by", "created_at")
    list_filter = ("status",)
    search_fields = ("common_name", "scientific_name")
    raw_id_fields = ("created_by", "hero_submission")
    readonly_fields = ("created_at", "updated_at")


def _decide(modeladmin, request, queryset, decision):
    for edit in queryset:
        try:
            decide_plant_edit(edit.pk, request.user, decision)
        except APIException as exc:
            modeladmin.message_user(request, f"#{edit.pk}: {exc.detail}", messages.WARNING)


@admin.action(description="Approve selected edits (applies them to the plant)")
def approve(modeladmin, request, queryset):
    _decide(modeladmin, request, queryset, Decision.APPROVE)


@admin.action(description="Reject selected edits")
def reject(modeladmin, request, queryset):
    _decide(modeladmin, request, queryset, Decision.REJECT)


@admin.register(PlantEdit)
class PlantEditAdmin(admin.ModelAdmin):
    list_display = ("id", "plant", "user", "status", "proposed_changes", "created_at")
    list_filter = ("status",)
    list_select_related = ("plant", "user")
    raw_id_fields = ("plant", "user")
    readonly_fields = ("status", "created_at", "updated_at")
    actions = [approve, reject]
