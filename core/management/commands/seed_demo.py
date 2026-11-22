"""
Fill a local database with demo plants, users and sightings around Melbourne.

    python manage.py seed_demo

Creates two demo accounts (a moderator and a contributor), approved sightings that show on
the map and calendar, and a couple of pending ones for the Review queue. Safe to run twice.
Refuses to run when DEBUG is off unless you pass --force.
"""
import random
import struct
import zlib
from datetime import date, timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.choices import Decision, PlantStatus
from core.params import point
from core.storage import LocalStorage, get_storage
from moderation.services import decide_submission
from plants.models import Plant
from submissions.models import Submission

MELBOURNE = (-37.8136, 144.9631)

# (common name, scientific name, description, bloom start (month, day), bloom end (month, day), colour)
PLANTS = [
    ("Golden Wattle", "Acacia pycnantha", "Australia's national floral emblem. Bright yellow puffball flowers.", (8, 1), (9, 30), (230, 190, 30)),
    ("Jacaranda", "Jacaranda mimosifolia", "Street tree covered in purple-blue flowers in late spring.", (11, 1), (12, 15), (140, 110, 210)),
    ("Common Heath", "Epacris impressa", "Victoria's floral emblem. Pink or white tube-shaped flowers.", (6, 1), (9, 30), (230, 120, 160)),
    ("Red Flowering Gum", "Corymbia ficifolia", "Small eucalypt with masses of red or orange flowers in summer.", (12, 15), (2, 28), (210, 50, 40)),
    ("Silver Banksia", "Banksia marginata", "Pale yellow cylinder-shaped flower spikes.", (1, 15), (6, 30), (220, 210, 120)),
    ("Crimson Bottlebrush", "Callistemon citrinus", "Bright red brush-like flower spikes loved by birds.", (10, 15), (12, 31), (200, 30, 60)),
    ("Japanese Cherry", "Prunus serrulata", "Ornamental cherry with pink blossom in early spring.", (9, 10), (10, 10), (250, 190, 200)),
    ("Waratah", "Telopea speciosissima", "Large red flower heads. Floral emblem of New South Wales.", (9, 20), (11, 10), (190, 20, 40)),
]


def placeholder_png(rgb, size=64):
    """A plain coloured square PNG, made without any image library."""
    raw = b"".join(b"\x00" + bytes(rgb) * size for _ in range(size))

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def window(year, start_md, end_md, jitter):
    start = date(year, *start_md) + timedelta(days=jitter)
    end_year = year + (end_md < start_md)   # windows like Dec -> Feb end next year
    end = date(end_year, *end_md) + timedelta(days=jitter)
    return start, max(end, start)


class Command(BaseCommand):
    help = "Create demo users, plants and sightings for local development."

    def add_arguments(self, parser):
        parser.add_argument("--password", default="bloom-demo-1234", help="Password for the demo accounts")
        parser.add_argument("--force", action="store_true", help="Run even when DEBUG is off")

    def handle(self, *args, **opts):
        if not settings.DEBUG and not opts["force"]:
            raise CommandError("Refusing to seed demo data with DEBUG off. Use --force if you really mean it.")

        User = get_user_model()
        rng = random.Random(42)
        storage = get_storage()
        year = date.today().year

        with transaction.atomic():
            mod, _ = User.objects.get_or_create(
                email="demo-moderator@bloom.local", defaults={"display_name": "Demo Moderator", "role": "moderator"}
            )
            user, _ = User.objects.get_or_create(
                email="demo-user@bloom.local", defaults={"display_name": "Demo Contributor"}
            )
            for account in (mod, user):
                account.set_password(opts["password"])
                account.save()

            if Submission.objects.filter(user=user).exists():
                self.stdout.write("Demo sightings already exist, skipping.")
                return

            def make_photo(n, rgb):
                ext = "png"
                key = f"submissions/{user.id}/seed/{n}.{ext}"
                if isinstance(storage, LocalStorage):
                    path = storage.path_for(key)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(placeholder_png(rgb))
                return key

            n = 0
            for common, sci, desc, start_md, end_md, rgb in PLANTS:
                plant, _ = Plant.objects.get_or_create(
                    scientific_name=sci,
                    defaults={"common_name": common, "description": desc, "status": PlantStatus.APPROVED},
                )
                for _ in range(3):
                    n += 1
                    lat = MELBOURNE[0] + rng.uniform(-0.15, 0.15)
                    lng = MELBOURNE[1] + rng.uniform(-0.2, 0.2)
                    start, end = window(year, start_md, end_md, rng.randint(-7, 7))
                    sub = Submission.objects.create(
                        user=user, plant=plant, location=point(lat, lng), bloom_start=start, bloom_end=end,
                        photo_key=make_photo(n, rgb), description=f"Demo sighting of {common}.",
                    )
                    decide_submission(sub.pk, mod, Decision.APPROVE)

            # Two pending items for the Review queue: an existing plant and a brand-new name
            wattle = Plant.objects.get(scientific_name="Acacia pycnantha")
            Submission.objects.create(
                user=user, plant=wattle, location=point(-37.88, 145.06), bloom_start=date(year, 8, 5),
                bloom_end=date(year, 9, 25), photo_key=make_photo(n + 1, (230, 190, 30)),
                description="Big tree by the station car park",
            )
            new_plant = Plant.objects.create(
                common_name="Purple tree on Neerim Rd", status=PlantStatus.PENDING, created_by=user
            )
            Submission.objects.create(
                user=user, plant=new_plant, location=point(-37.885, 145.065), bloom_start=date(year, 11, 1),
                bloom_end=date(year, 11, 30), photo_key=make_photo(n + 2, (150, 90, 200)),
            )

        self.stdout.write(self.style.SUCCESS(
            f"Seeded {len(PLANTS)} plants, {n} approved + 2 pending sightings.\n"
            f"Demo logins: demo-moderator@bloom.local / demo-user@bloom.local (password from --password)."
        ))
