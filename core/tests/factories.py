"""Tiny helpers to build test data. Not a test module itself."""
import shutil
import tempfile
from datetime import timedelta
from itertools import count

from django.contrib.auth import get_user_model
from django.test import override_settings
from django.utils import timezone

from core.choices import ModerationStatus, PlantStatus
from core.params import point
from core.storage import get_storage
from plants.models import Plant
from submissions.models import Submission

_n = count(1)
MELBOURNE = (-37.8136, 144.9631)


def make_user(**extra):
    n = next(_n)
    extra.setdefault("display_name", f"User {n}")
    return get_user_model().objects.create_user(email=f"user{n}@example.com", password="pw-not-used-1234", **extra)


def make_moderator(**extra):
    return make_user(role="moderator", **extra)


def make_plant(name="Golden Wattle", scientific=None, status=PlantStatus.APPROVED, **extra):
    return Plant.objects.create(common_name=name, scientific_name=scientific, status=status, **extra)


def make_submission(user=None, plant=None, lat=MELBOURNE[0], lng=MELBOURNE[1], start=None, end=None,
                    status=ModerationStatus.PENDING, **extra):
    today = timezone.localdate()
    start = start or today - timedelta(days=5)
    end = end or start + timedelta(days=30)
    return Submission.objects.create(
        user=user or make_user(),
        plant=plant or make_plant(),
        location=point(lat, lng),
        bloom_start=start,
        bloom_end=end,
        status=status,
        photo_key=extra.pop("photo_key", "submissions/0/test.jpg"),
        **extra,
    )


class TempMediaMixin:
    """Points local photo storage at a temp folder for the test class."""

    @classmethod
    def setUpClass(cls):
        cls._media = tempfile.mkdtemp()
        cls._media_override = override_settings(MEDIA_ROOT=cls._media, PHOTO_STORAGE="local")
        cls._media_override.enable()
        get_storage.cache_clear()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._media_override.disable()
        get_storage.cache_clear()
        shutil.rmtree(cls._media, ignore_errors=True)

    def put_photo(self, key, data=b"\xff\xd8\xff fake jpeg"):
        path = get_storage().path_for(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return key
