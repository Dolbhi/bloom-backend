from django.urls import path

from .views import MeView, PublicUserView

urlpatterns = [
    path("me", MeView.as_view(), name="users-me"),
    path("<int:pk>", PublicUserView.as_view(), name="users-detail"),
]
