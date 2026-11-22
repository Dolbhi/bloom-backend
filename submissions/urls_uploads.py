from django.urls import path

from .views import PresignView, local_upload

urlpatterns = [
    path("presign", PresignView.as_view(), name="uploads-presign"),
    path("local/<str:token>", local_upload, name="local-upload"),
]
