"""Parsing helpers for query-string parameters. Every error is a 400 with a field message."""
from django.contrib.gis.geos import Point
from rest_framework.exceptions import ValidationError


def _float(params, name, low, high, required=False):
    raw = params.get(name)
    if raw in (None, ""):
        if required:
            raise ValidationError({name: ["This parameter is required."]})
        return None
    try:
        value = float(raw)
    except ValueError:
        raise ValidationError({name: ["Must be a number."]})
    if not low <= value <= high:
        raise ValidationError({name: [f"Must be between {low} and {high}."]})
    return value


def lat_lng(params, required=False):
    """Reads ?lat=..&lng=.. Returns (lat, lng) or (None, None). Both or neither."""
    lat = _float(params, "lat", -90, 90, required)
    lng = _float(params, "lng", -180, 180, required)
    if (lat is None) != (lng is None):
        raise ValidationError({"lat": ["Send both lat and lng, or neither."]})
    return lat, lng


def point(lat, lng):
    """⚠️ GeoDjango points are (x=longitude, y=latitude)."""
    return Point(lng, lat, srid=4326)


def bbox(params):
    """?bbox=minLng,minLat,maxLng,maxLat -> tuple of 4 floats."""
    raw = params.get("bbox")
    if not raw:
        raise ValidationError({"bbox": ["This parameter is required: minLng,minLat,maxLng,maxLat."]})
    try:
        min_lng, min_lat, max_lng, max_lat = (float(v) for v in raw.split(","))
    except ValueError:
        raise ValidationError({"bbox": ["Format: minLng,minLat,maxLng,maxLat."]})
    if not (-180 <= min_lng <= 180 and -180 <= max_lng <= 180 and -90 <= min_lat <= 90 and -90 <= max_lat <= 90):
        raise ValidationError({"bbox": ["Coordinates out of range."]})
    if min_lng >= max_lng or min_lat >= max_lat:
        raise ValidationError({"bbox": ["Min values must be smaller than max values."]})
    return min_lng, min_lat, max_lng, max_lat


def near(params):
    """?near=lat,lng&radius_km=10 -> (Point, km) or None."""
    raw = params.get("near")
    if not raw:
        return None
    try:
        lat, lng = (float(v) for v in raw.split(","))
    except ValueError:
        raise ValidationError({"near": ["Format: lat,lng."]})
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        raise ValidationError({"near": ["Coordinates out of range."]})
    km = _float(params, "radius_km", 0.01, 20000, required=True)
    return point(lat, lng), km


def boolean(params, name):
    raw = params.get(name)
    if raw is None:
        return None
    if raw.lower() in ("true", "1", "yes"):
        return True
    if raw.lower() in ("false", "0", "no"):
        return False
    raise ValidationError({name: ["Must be true or false."]})


def positive_int(params, name):
    raw = params.get(name)
    if raw in (None, ""):
        return None
    if not raw.isdigit():
        raise ValidationError({name: ["Must be a positive whole number."]})
    return int(raw)


def choice(params, name, options):
    raw = params.get(name)
    if raw in (None, ""):
        return None
    if raw not in options:
        raise ValidationError({name: [f"Must be one of: {', '.join(options)}."]})
    return raw
