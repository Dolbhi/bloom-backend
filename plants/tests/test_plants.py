from datetime import timedelta

from django.utils import timezone
from rest_framework.test import APITestCase

from core.tests.factories import make_moderator, make_plant, make_submission, make_user
from plants.models import PlantEdit


class PlantListTests(APITestCase):
    def test_lists_approved_plants_in_model_order(self):
        second = make_plant("Silver Wattle", "Acacia dealbata", description="Silver flowers")
        first = make_plant("Golden Wattle", "Acacia pycnantha", description="Golden flowers")
        make_plant("Pending plant", status="pending")

        res = self.client.get("/api/v1/plants")

        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(
            res.data,
            [
                {
                    "id": first.id,
                    "common_name": "Golden Wattle",
                    "scientific_name": "Acacia pycnantha",
                    "description": "Golden flowers",
                },
                {
                    "id": second.id,
                    "common_name": "Silver Wattle",
                    "scientific_name": "Acacia dealbata",
                    "description": "Silver flowers",
                },
            ],
        )


class SearchTests(APITestCase):
    def setUp(self):
        self.golden = make_plant("Golden Wattle", "Acacia pycnantha")
        self.silver = make_plant("Silver Wattle", "Acacia dealbata")
        make_plant("Jacaranda", "Jacaranda mimosifolia")

    def search(self, q):
        res = self.client.get("/api/v1/plants/search", {"q": q})
        self.assertEqual(res.status_code, 200, res.data)
        return [p["id"] for p in res.data]

    def test_prefix_and_fuzzy(self):
        self.assertEqual(set(self.search("wat")), {self.golden.id, self.silver.id})
        self.assertIn(self.golden.id, self.search("wattel"))      # typo still matches
        self.assertIn(self.golden.id, self.search("pycnantha"))   # scientific name

    def test_too_short(self):
        self.assertEqual(self.client.get("/api/v1/plants/search", {"q": "w"}).status_code, 400)

    def test_pending_plants_only_for_creator(self):
        creator = make_user()
        pending = make_plant("Wattle-ish thing", status="pending", created_by=creator)
        self.assertNotIn(pending.id, self.search("wattle"))
        self.client.force_authenticate(creator)
        results = self.search("wattle")
        self.assertIn(pending.id, results)
        self.assertEqual(results[-1], pending.id)   # approved first


class DetailTests(APITestCase):
    def test_full_details_with_prediction(self):
        plant = make_plant("Golden Wattle", "Acacia pycnantha")
        today = timezone.localdate()
        for _ in range(3):
            make_submission(plant=plant, status="approved", start=today - timedelta(days=5), end=today + timedelta(days=20))
        make_submission(plant=plant)   # pending: not counted
        res = self.client.get(f"/api/v1/plants/{plant.id}", {"lat": -37.81, "lng": 144.96})
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data["prediction"]["based_on"], 3)
        self.assertEqual(res.data["prediction"]["bloom_status"], "blooming_now")
        self.assertIn("within 50 km", res.data["prediction"]["summary"])
        self.assertEqual(len(res.data["locations"]), 3)
        self.assertEqual(res.data["submissions"]["count"], 3)
        self.assertIsNotNone(res.data["hero_photo_url"])

    def test_no_sightings_means_null_prediction(self):
        plant = make_plant()
        self.assertIsNone(self.client.get(f"/api/v1/plants/{plant.id}").data["prediction"])

    def test_far_away_sightings_ignored_with_location(self):
        plant = make_plant()
        make_submission(plant=plant, status="approved", lat=-33.86, lng=151.21)   # Sydney
        res = self.client.get(f"/api/v1/plants/{plant.id}", {"lat": -37.81, "lng": 144.96})
        self.assertIsNone(res.data["prediction"])

    def test_pending_plant_hidden(self):
        creator = make_user()
        plant = make_plant("New", status="pending", created_by=creator)
        url = f"/api/v1/plants/{plant.id}"
        self.assertEqual(self.client.get(url).status_code, 404)
        self.client.force_authenticate(creator)
        self.assertEqual(self.client.get(url).status_code, 200)
        self.client.force_authenticate(make_moderator())
        self.assertEqual(self.client.get(url).status_code, 200)


class SuggestEditTests(APITestCase):
    def test_create_edit(self):
        plant = make_plant()
        self.client.force_authenticate(make_user())
        res = self.client.post(f"/api/v1/plants/{plant.id}/edits",
                               {"proposed_changes": {"scientific_name": "Acacia pycnantha"}, "reason": "Latin name"})
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(PlantEdit.objects.get().status, "pending")

    def test_rejects_unknown_or_empty(self):
        plant = make_plant()
        self.client.force_authenticate(make_user())
        for changes in ({}, {"status": "approved"}, {"common_name": ""}):
            res = self.client.post(f"/api/v1/plants/{plant.id}/edits", {"proposed_changes": changes})
            self.assertEqual(res.status_code, 400, changes)


class CalendarTests(APITestCase):
    def test_now_soon_timeline(self):
        today = timezone.localdate()
        now_plant = make_plant("Now Plant")
        soon_plant = make_plant("Soon Plant")
        make_submission(plant=now_plant, status="approved", start=today - timedelta(days=5), end=today + timedelta(days=10))
        make_submission(plant=soon_plant, status="approved", start=today + timedelta(days=10), end=today + timedelta(days=40))
        res = self.client.get("/api/v1/calendar", {"lat": -37.81, "lng": 144.96})
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data["hemisphere"], "southern")
        self.assertEqual([p["common_name"] for p in res.data["blooming_now"]], ["Now Plant"])
        self.assertEqual(res.data["blooming_soon"][0]["common_name"], "Soon Plant")
        self.assertEqual(res.data["blooming_soon"][0]["starts_in_days"], 10)
        self.assertIn("Now Plant", [p["common_name"] for p in res.data["timeline"]])

    def test_requires_location(self):
        self.assertEqual(self.client.get("/api/v1/calendar").status_code, 400)

    def test_explicit_season(self):
        res = self.client.get("/api/v1/calendar", {"lat": 51.5, "lng": -0.1, "season": "winter"})
        self.assertEqual(res.data["months"], ["12", "01", "02"])
        self.assertEqual(res.data["hemisphere"], "northern")
