"""
Bloom prediction (F9).

Takes the approved bloom windows for a plant (optionally only sightings within ~50 km of the
user), turns each start and end into a day-of-year, and takes the circular average of the
starts and of the ends. Calculated on request; cache later only if it gets slow.
"""
from collections import defaultdict

from django.conf import settings
from django.contrib.gis.measure import D
from django.utils import timezone

from core import bloom
from core.choices import ModerationStatus, PlantStatus
from core.params import point
from submissions.models import Submission


def predict_from_windows(windows, today, within_km=None):
    """windows: list of (bloom_start, bloom_end) dates. Returns the prediction dict or None."""
    if not windows:
        return None
    start = bloom.circular_mean_doy([bloom.day_of_year(s) for s, _ in windows])
    end = bloom.circular_mean_doy([bloom.day_of_year(e) for _, e in windows])
    status, starts_in = bloom.window_status(
        bloom.day_of_year(today), start, end, settings.BLOOM["BLOOMING_SOON_DAYS"]
    )
    n = len(windows)
    where = f" within {within_km} km" if within_km else ""
    result = {
        "start": bloom.doy_to_mmdd(start),
        "end": bloom.doy_to_mmdd(end),
        "based_on": n,
        "bloom_status": status,
        "summary": (
            f"Usually blooms {bloom.describe_doy(start)} to {bloom.describe_doy(end)} "
            f"({n} sighting{'s' if n != 1 else ''}{where})"
        ),
        "_start_doy": start,
        "_end_doy": end,
    }
    if starts_in is not None:
        result["starts_in_days"] = starts_in
    return result


def public(prediction):
    """Drop internal keys before sending to the app."""
    if prediction is None:
        return None
    return {k: v for k, v in prediction.items() if not k.startswith("_")}


def _approved(lat=None, lng=None):
    qs = Submission.objects.filter(status=ModerationStatus.APPROVED)
    if lat is not None:
        qs = qs.filter(location__dwithin=(point(lat, lng), D(km=settings.BLOOM["PREDICTION_RADIUS_KM"])))
    return qs


def predict_for_plant(plant_id, lat=None, lng=None, today=None):
    today = today or timezone.localdate()
    windows = list(_approved(lat, lng).filter(plant_id=plant_id).values_list("bloom_start", "bloom_end"))
    km = settings.BLOOM["PREDICTION_RADIUS_KM"] if lat is not None else None
    return predict_from_windows(windows, today, km)


def predict_nearby(lat, lng, today=None):
    """Prediction for every approved plant with approved sightings near (lat, lng).
    Returns list of (plant_id, common_name, prediction)."""
    today = today or timezone.localdate()
    rows = (
        _approved(lat, lng)
        .filter(plant__status=PlantStatus.APPROVED)
        .values_list("plant_id", "plant__common_name", "bloom_start", "bloom_end")
    )
    grouped = defaultdict(list)
    names = {}
    for plant_id, name, start, end in rows:
        grouped[plant_id].append((start, end))
        names[plant_id] = name
    km = settings.BLOOM["PREDICTION_RADIUS_KM"]
    results = [(pid, names[pid], predict_from_windows(windows, today, km)) for pid, windows in grouped.items()]
    return sorted(results, key=lambda r: r[1].lower())
