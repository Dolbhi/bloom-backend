from django.urls import path

from .views import MapPinsView

urlpatterns = [
    path("pins", MapPinsView.as_view(), name="map-pins"),
]
