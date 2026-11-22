from django.contrib import admin, messages
from django.contrib.gis.admin import GISModelAdmin
from django.utils.html import format_html
from rest_framework.exceptions import APIException

from core.choices import Decision
from core.storage import photo_url
from moderation.services import decide_submission

from .models import Submission


def _decide(modeladmin, request, queryset, decision):
    done = 0
    for submission in queryset:
        try:
            decide_submission(submission.pk, request.user, decision)
            done += 1
        except APIException as exc:
            modeladmin.message_user(request, f"#{submission.pk}: {exc.detail}", messages.WARNING)
    if done:
        modeladmin.message_user(request, f"{decision}: {done} submission(s).", messages.SUCCESS)


@admin.action(description="Approve selected (updates reputation)")
def approve(modeladmin, request, queryset):
    _decide(modeladmin, request, queryset, Decision.APPROVE)


@admin.action(description="Reject selected as spam (updates reputation)")
def reject(modeladmin, request, queryset):
    _decide(modeladmin, request, queryset, Decision.REJECT)


@admin.register(Submission)
class SubmissionAdmin(GISModelAdmin):
    list_display = ("id", "thumb", "plant", "user", "status", "revision", "bloom_start", "bloom_end", "created_at")
    list_filter = ("status",)
    search_fields = ("plant__common_name", "user__email", "description")
    list_select_related = ("plant", "user")
    autocomplete_fields = ("plant", "user")
    readonly_fields = ("photo", "status", "revision", "created_at", "updated_at")
    actions = [approve, reject]
    ordering = ("-created_at",)

    @admin.display(description="Photo")
    def thumb(self, obj):
        url = photo_url(obj.photo_key)
        return format_html('<img src="{}" style="height:40px">', url) if url else "-"

    @admin.display(description="Photo")
    def photo(self, obj):
        url = photo_url(obj.photo_key)
        return format_html('<img src="{}" style="max-height:300px">', url) if url else "-"
