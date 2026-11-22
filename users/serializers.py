from django.contrib.auth import password_validation
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers
from rest_framework_simplejwt.tokens import RefreshToken

from core.exceptions import Conflict

from .models import User


class UserSerializer(serializers.ModelSerializer):
    """The logged-in user's own account (includes email)."""

    can_moderate = serializers.BooleanField(read_only=True)

    class Meta:
        model = User
        fields = ["id", "email", "display_name", "reputation", "role", "can_moderate"]
        read_only_fields = ["id", "email", "reputation", "role"]


class SignupSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, trim_whitespace=False)
    display_name = serializers.CharField(max_length=50, required=False, allow_blank=True, default="")

    def validate_email(self, value):
        value = User.objects.normalize_email(value)
        if User.objects.filter(email__iexact=value).exists():
            raise Conflict("An account with this email already exists.")
        return value

    def validate(self, attrs):
        candidate = User(email=attrs["email"], display_name=attrs.get("display_name", ""))
        try:
            password_validation.validate_password(attrs["password"], candidate)
        except DjangoValidationError as exc:   # weak password -> DRF field error
            raise serializers.ValidationError({"password": list(exc.messages)})
        return attrs

    def create(self, validated_data):
        return User.objects.create_user(**validated_data)


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, trim_whitespace=False)


class RefreshSerializer(serializers.Serializer):
    refresh = serializers.CharField()


class AuthResponseSerializer(serializers.Serializer):
    user = UserSerializer()
    access = serializers.CharField()
    refresh = serializers.CharField()


def auth_payload(user):
    refresh = RefreshToken.for_user(user)
    return {"user": UserSerializer(user).data, "access": str(refresh.access_token), "refresh": str(refresh)}


class PublicUserSerializer(serializers.ModelSerializer):
    """Contributor profile (F14). Never includes the email."""

    display_name = serializers.CharField(source="public_name")

    class Meta:
        model = User
        fields = ["id", "display_name", "reputation", "date_joined"]
