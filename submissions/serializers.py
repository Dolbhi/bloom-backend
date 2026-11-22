from django.conf import settings
from django.db import transaction
from django.db.models import Prefetch
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from core.choices import ModerationStatus, PlantStatus
from core.params import point
from core.permissions import is_moderator
from core.serializers import ContributorSerializer, PlantMiniSerializer, PlantMiniStatusSerializer, ReviewMiniSerializer
from core.storage import get_storage, key_belongs_to, photo_url
from moderation.models import Review
from plants.models import Plant

from .models import MAX_WINDOW_DAYS, Submission


def with_latest_review(queryset):
    """Prefetch reviews newest-first so `latest_review` doesn't cost one query per row."""
    return queryset.prefetch_related(
        Prefetch("reviews", queryset=Review.objects.order_by("-created_at"), to_attr="ordered_reviews")
    )


def latest_review_of(submission):
    reviews = getattr(submission, "ordered_reviews", None)
    if reviews is None:
        reviews = list(submission.reviews.order_by("-created_at")[:1])
    return ReviewMiniSerializer(reviews[0]).data if reviews else None


# --- Read shapes ------------------------------------------------------------

class _SubmissionRead(serializers.ModelSerializer):
    photo_url = serializers.SerializerMethodField()
    lat = serializers.FloatField(read_only=True)
    lng = serializers.FloatField(read_only=True)

    @extend_schema_field(serializers.URLField(allow_null=True))
    def get_photo_url(self, obj):
        return photo_url(obj.photo_key, self.context.get("request"))


class MySubmissionSerializer(_SubmissionRead):
    """Profile list: own submissions with status badge + latest reviewer comment."""

    plant = PlantMiniStatusSerializer()
    latest_review = serializers.SerializerMethodField()

    class Meta:
        model = Submission
        fields = ["id", "plant", "photo_url", "status", "revision", "lat", "lng", "bloom_start", "bloom_end",
                  "description", "latest_review", "created_at", "updated_at"]

    @extend_schema_field(ReviewMiniSerializer(allow_null=True))
    def get_latest_review(self, obj):
        return latest_review_of(obj)


class GallerySubmissionSerializer(_SubmissionRead):
    """Public sighting card: plant gallery, contributor profile."""

    plant = PlantMiniSerializer()
    contributor = ContributorSerializer(source="user")

    class Meta:
        model = Submission
        fields = ["id", "plant", "photo_url", "bloom_start", "bloom_end", "contributor", "created_at"]


class SubmissionDetailSerializer(_SubmissionRead):
    plant = PlantMiniStatusSerializer()
    contributor = ContributorSerializer(source="user")
    latest_review = serializers.SerializerMethodField()

    class Meta:
        model = Submission
        fields = ["id", "status", "revision", "plant", "photo_url", "lat", "lng", "bloom_start", "bloom_end",
                  "description", "contributor", "latest_review", "created_at", "updated_at"]

    @extend_schema_field(ReviewMiniSerializer(allow_null=True))
    def get_latest_review(self, obj):
        user = self.context["request"].user
        # Reviewer comments are for the contributor (and moderators), not the public
        if user.is_authenticated and (obj.user_id == user.id or is_moderator(user)):
            return latest_review_of(obj)
        return None


# --- Write ------------------------------------------------------------------

class SubmissionWriteSerializer(serializers.Serializer):
    """POST /submissions (create) and PATCH /submissions/{id} (edit + resubmit, partial)."""

    plant_id = serializers.IntegerField(required=False)
    new_plant_name = serializers.CharField(required=False, max_length=120)
    photo_key = serializers.CharField(max_length=255)
    lat = serializers.FloatField(min_value=-90, max_value=90)
    lng = serializers.FloatField(min_value=-180, max_value=180)
    bloom_start = serializers.DateField()
    bloom_end = serializers.DateField()
    description = serializers.CharField(required=False, allow_blank=True, max_length=2000)

    def validate_new_plant_name(self, value):
        value = " ".join(value.split())
        if len(value) < 2:
            raise serializers.ValidationError("Plant name must be at least 2 characters.")
        return value

    def validate(self, attrs):
        user = self.context["request"].user
        instance = self.instance

        # Plant: exactly one of plant_id / new_plant_name (on edit: at most one)
        has_id, has_name = "plant_id" in attrs, "new_plant_name" in attrs
        if has_id and has_name:
            raise serializers.ValidationError({"plant_id": ["Send plant_id or new_plant_name, not both."]})
        if instance is None and not (has_id or has_name):
            raise serializers.ValidationError({"plant_id": ["Pick a plant (plant_id) or type a new name (new_plant_name)."]})
        if has_id:
            plant = Plant.objects.filter(pk=attrs["plant_id"]).first()
            if plant is None or not plant.visible_to(user):
                raise serializers.ValidationError({"plant_id": ["Plant not found."]})
            attrs["plant"] = plant

        # Location: both or neither when editing
        if instance is not None and (("lat" in attrs) != ("lng" in attrs)):
            raise serializers.ValidationError({"lat": ["Send both lat and lng."]})

        # Bloom window
        start = attrs.get("bloom_start", getattr(instance, "bloom_start", None))
        end = attrs.get("bloom_end", getattr(instance, "bloom_end", None))
        if start and end:
            if end < start:
                raise serializers.ValidationError({"bloom_end": ["Bloom end must be on or after bloom start."]})
            if (end - start).days > MAX_WINDOW_DAYS:
                raise serializers.ValidationError({"bloom_end": [f"Bloom window can be at most {MAX_WINDOW_DAYS} days."]})

        # Photo: issued to this user and actually uploaded
        key = attrs.get("photo_key")
        if key is not None and not (instance is not None and key == instance.photo_key):
            if not key_belongs_to(key, user.id):
                raise serializers.ValidationError({"photo_key": ["This photo key was not issued to you."]})
            storage = get_storage()
            if not storage.exists(key):
                raise serializers.ValidationError({"photo_key": ["Photo not found in storage. Upload it first."]})
            if storage.size(key) > settings.PHOTO_MAX_BYTES:
                raise serializers.ValidationError({"photo_key": ["Photo is larger than the size limit."]})
        return attrs

    def _plant_for(self, attrs, user):
        if "plant" in attrs:
            return attrs["plant"]
        name = attrs["new_plant_name"]
        # Reuse the user's own pending plant with the same name instead of creating duplicates
        existing = Plant.objects.filter(
            common_name__iexact=name, status=PlantStatus.PENDING, created_by=user
        ).first()
        return existing or Plant.objects.create(common_name=name, status=PlantStatus.PENDING, created_by=user)

    @transaction.atomic
    def create(self, validated_data):
        user = self.context["request"].user
        return Submission.objects.create(
            user=user,
            plant=self._plant_for(validated_data, user),
            location=point(validated_data["lat"], validated_data["lng"]),
            bloom_start=validated_data["bloom_start"],
            bloom_end=validated_data["bloom_end"],
            description=validated_data.get("description", ""),
            photo_key=validated_data["photo_key"],
        )

    def update(self, instance, validated_data):
        """Apply edits, then send it back to the queue as a new revision."""
        user = self.context["request"].user
        if "plant" in validated_data or "new_plant_name" in validated_data:
            instance.plant = self._plant_for(validated_data, user)
        if "lat" in validated_data:
            instance.location = point(validated_data["lat"], validated_data["lng"])
        for field in ("bloom_start", "bloom_end", "description", "photo_key"):
            if field in validated_data:
                setattr(instance, field, validated_data[field])
        instance.status = ModerationStatus.PENDING
        instance.revision += 1
        instance.save()
        return instance


class SubmissionCreatedSerializer(serializers.ModelSerializer):
    plant = PlantMiniStatusSerializer()

    class Meta:
        model = Submission
        fields = ["id", "status", "revision", "plant", "created_at"]


# --- Uploads ----------------------------------------------------------------

class PresignRequestSerializer(serializers.Serializer):
    content_type = serializers.ChoiceField(choices=list(settings.PHOTO_ALLOWED_TYPES))
    size_bytes = serializers.IntegerField(min_value=1)

    def validate_size_bytes(self, value):
        if value > settings.PHOTO_MAX_BYTES:
            raise serializers.ValidationError(f"Photo must be at most {settings.PHOTO_MAX_BYTES // (1024 * 1024)} MB.")
        return value


class PresignResponseSerializer(serializers.Serializer):
    upload_url = serializers.URLField()
    photo_key = serializers.CharField()
    expires_in = serializers.IntegerField()
    method = serializers.CharField()
    headers = serializers.DictField(child=serializers.CharField())
