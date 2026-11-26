from rest_framework import serializers

from .models import EDITABLE_PLANT_FIELDS, Plant, PlantEdit

FIELD_LIMITS = {"common_name": 120, "scientific_name": 200, "description": 5000}


class PlantSearchSerializer(serializers.ModelSerializer):
    class Meta:
        model = Plant
        fields = ["id", "common_name", "scientific_name", "status"]


class PlantListSerializer(serializers.ModelSerializer):
    class Meta:
        model = Plant
        fields = ["id", "common_name", "scientific_name", "description"]


class PlantEditCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlantEdit
        fields = ["id", "proposed_changes", "reason", "status", "created_at"]
        read_only_fields = ["id", "status", "created_at"]

    def validate_proposed_changes(self, value):
        if not isinstance(value, dict) or not value:
            raise serializers.ValidationError("Must be a non-empty object.")
        unknown = set(value) - set(EDITABLE_PLANT_FIELDS)
        if unknown:
            raise serializers.ValidationError(
                f"Unknown field(s): {', '.join(sorted(unknown))}. Allowed: {', '.join(EDITABLE_PLANT_FIELDS)}."
            )
        cleaned = {}
        for key, val in value.items():
            if not isinstance(val, str):
                raise serializers.ValidationError(f"{key} must be text.")
            val = val.strip()
            if key == "common_name" and not val:
                raise serializers.ValidationError("common_name cannot be empty.")
            if len(val) > FIELD_LIMITS[key]:
                raise serializers.ValidationError(f"{key} must be at most {FIELD_LIMITS[key]} characters.")
            cleaned[key] = val
        return cleaned
