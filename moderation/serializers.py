from django.conf import settings
from rest_framework import serializers

from core.choices import Decision

from .models import Review


class DecisionSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(choices=Decision.choices)
    comment = serializers.CharField(required=False, allow_blank=True, default="", max_length=2000)

    def validate(self, attrs):
        if attrs["decision"] == Decision.REQUEST_CHANGES and not attrs.get("comment", "").strip():
            raise serializers.ValidationError({"comment": ["A comment is required when requesting changes."]})
        return attrs


def contributor_block(user):
    return {
        "id": user.id,
        "display_name": user.public_name,
        "reputation": user.reputation,
        # Low reputation -> the app can show a warning so the moderator looks more carefully (F8)
        "low_reputation": user.reputation < settings.BLOOM["LOW_REPUTATION"],
    }


class ReviewHistorySerializer(serializers.ModelSerializer):
    reviewer = serializers.SerializerMethodField()

    class Meta:
        model = Review
        fields = ["id", "decision", "comment", "submission_revision", "reviewer", "created_at"]

    def get_reviewer(self, obj) -> dict:
        return {"id": obj.reviewer_id, "display_name": obj.reviewer.public_name}
