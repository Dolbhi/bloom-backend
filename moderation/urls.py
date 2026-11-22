from django.urls import path

from .views import (
    PlantEditDecisionView,
    PlantEditReviewView,
    QueueView,
    SubmissionDecisionView,
    SubmissionReviewView,
)

urlpatterns = [
    path("queue", QueueView.as_view(), name="moderation-queue"),
    path("submissions/<int:pk>", SubmissionReviewView.as_view(), name="moderation-submission"),
    path("submissions/<int:pk>/decision", SubmissionDecisionView.as_view(), name="moderation-submission-decision"),
    path("plant-edits/<int:pk>", PlantEditReviewView.as_view(), name="moderation-plant-edit"),
    path("plant-edits/<int:pk>/decision", PlantEditDecisionView.as_view(), name="moderation-plant-edit-decision"),
]
