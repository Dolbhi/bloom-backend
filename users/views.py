from django.contrib.auth import authenticate
from django.contrib.auth.models import update_last_login
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers, status
from rest_framework.exceptions import AuthenticationFailed, ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from core.choices import ModerationStatus
from core.serializers import paginate_nested
from submissions.models import Submission
from submissions.serializers import GallerySubmissionSerializer, MySubmissionSerializer, with_latest_review

from .models import User
from .serializers import (
    AuthResponseSerializer,
    LoginSerializer,
    PublicUserSerializer,
    RefreshSerializer,
    SignupSerializer,
    UserSerializer,
    auth_payload,
)


class SignupView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth"

    @extend_schema(request=SignupSerializer, responses={201: AuthResponseSerializer}, tags=["auth"])
    def post(self, request):
        serializer = SignupSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        update_last_login(None, user)
        return Response(auth_payload(user), status=status.HTTP_201_CREATED)


class LoginView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth"

    @extend_schema(request=LoginSerializer, responses={200: AuthResponseSerializer}, tags=["auth"])
    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = authenticate(request, email=serializer.validated_data["email"], password=serializer.validated_data["password"])
        if user is None:
            # Same message for wrong email and wrong password, so nobody can probe which emails exist
            raise AuthenticationFailed("Email or password is incorrect.")
        update_last_login(None, user)
        return Response(auth_payload(user))


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=RefreshSerializer, responses={204: None}, tags=["auth"])
    def post(self, request):
        serializer = RefreshSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            token = RefreshToken(serializer.validated_data["refresh"])
            if str(token["user_id"]) != str(request.user.id):
                raise ValidationError({"refresh": ["This token belongs to another user."]})
            token.blacklist()
        except TokenError as exc:
            raise ValidationError({"refresh": [str(exc)]})
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def _payload(self, request):
        data = UserSerializer(request.user).data
        submissions = with_latest_review(
            Submission.objects.filter(user=request.user).select_related("plant").order_by("-created_at")
        )
        data["submissions"] = MySubmissionSerializer(submissions, many=True, context={"request": request}).data
        return data

    @extend_schema(
        responses=inline_serializer("Me", {
            "id": serializers.IntegerField(), "email": serializers.EmailField(),
            "display_name": serializers.CharField(), "reputation": serializers.IntegerField(),
            "role": serializers.CharField(), "can_moderate": serializers.BooleanField(),
            "submissions": MySubmissionSerializer(many=True),
        }),
        tags=["users"],
    )
    def get(self, request):
        return Response(self._payload(request))

    @extend_schema(request=UserSerializer, responses=UserSerializer, tags=["users"])
    def patch(self, request):
        serializer = UserSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(self._payload(request))


class PublicUserView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(
        responses=inline_serializer("PublicProfile", {
            "id": serializers.IntegerField(), "display_name": serializers.CharField(),
            "reputation": serializers.IntegerField(), "date_joined": serializers.DateTimeField(),
            "submissions": inline_serializer("PublicProfileSubmissions", {
                "count": serializers.IntegerField(), "next": serializers.CharField(allow_null=True),
                "previous": serializers.CharField(allow_null=True),
                "results": GallerySubmissionSerializer(many=True),
            }),
        }),
        tags=["users"],
    )
    def get(self, request, pk):
        user = get_object_or_404(User, pk=pk, is_active=True)
        data = PublicUserSerializer(user).data
        approved = (
            Submission.objects.filter(user=user, status=ModerationStatus.APPROVED)
            .select_related("plant", "user")
            .order_by("-created_at")
        )
        data["submissions"] = paginate_nested(request, approved, GallerySubmissionSerializer, {"request": request})
        return Response(data)
