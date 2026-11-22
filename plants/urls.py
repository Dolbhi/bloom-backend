from django.urls import path

from .views import PlantDetailView, PlantEditCreateView, PlantSearchView

urlpatterns = [
    path("search", PlantSearchView.as_view(), name="plants-search"),
    path("<int:pk>", PlantDetailView.as_view(), name="plants-detail"),
    path("<int:pk>/edits", PlantEditCreateView.as_view(), name="plants-edits"),
]
