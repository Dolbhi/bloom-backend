from django.urls import path

from .views import SubmissionDetailView

urlpatterns = [
    path("<int:pk>", SubmissionDetailView.as_view(), name="submissions-detail"),
]
