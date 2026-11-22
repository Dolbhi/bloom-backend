from datetime import timedelta

from django.utils import timezone
from rest_framework.test import APITestCase

from core.tests.factories import make_plant, make_submission

# A box around Melbourne
BBOX = "144.5,-38.2,145.5,-37.5"


class MapPinsTests(APITestCase):
    def setUp(self):
        self.today = timezone.localdate()
        self.wattle = make_plant("Golden Wattle")
        self.jacaranda = make_plant("Jacaranda")

    def pins(self, **params):
        res = self.client.get("/api/v1/map/pins", {"bbox": BBOX, **params})
        self.assertEqual(res.status_code, 200, res.data)
        return {p["id"] for p in res.data["results"]}

    def test_only_approved_inside_box(self):
        inside = make_submission(plant=self.wattle, status="approved")
        make_submission(plant=self.wattle)   # pending
        outside = make_submission(plant=self.wattle, status="approved", lat=-33.86, lng=151.21)   # Sydney
        self.assertEqual(self.pins(), {inside.id})
        self.assertNotIn(outside.id, self.pins())

    def test_pin_shape(self):
        s = make_submission(plant=self.wattle, status="approved", lat=-37.88, lng=145.06)
        pin = self.client.get("/api/v1/map/pins", {"bbox": BBOX}).data["results"][0]
        self.assertEqual(pin["id"], s.id)
        self.assertAlmostEqual(pin["lat"], -37.88)
        self.assertAlmostEqual(pin["lng"], 145.06)
        self.assertEqual(pin["plant"]["common_name"], "Golden Wattle")
        self.assertEqual(pin["bloom_status"], "blooming_now")

    def test_plant_filter(self):
        a = make_submission(plant=self.wattle, status="approved")
        make_submission(plant=self.jacaranda, status="approved")
        self.assertEqual(self.pins(plant=self.wattle.id), {a.id})

    def test_blooming_now_filter(self):
        now = make_submission(status="approved", start=self.today - timedelta(days=3), end=self.today + timedelta(days=3))
        later = make_submission(status="approved", start=self.today + timedelta(days=60), end=self.today + timedelta(days=90))
        self.assertEqual(self.pins(blooming_now="true"), {now.id})
        self.assertEqual(self.pins(blooming_now="false"), {later.id})

    def test_blooming_now_matches_previous_years(self):
        last_year = make_submission(status="approved", start=self.today - timedelta(days=367), end=self.today - timedelta(days=360))
        self.assertEqual(self.pins(blooming_now="true"), {last_year.id})

    def test_season_filter(self):
        year = self.today.year
        spring = make_submission(status="approved", start=self.today.replace(year=year, month=9, day=10),
                                 end=self.today.replace(year=year, month=10, day=10))
        summer_wrap = make_submission(status="approved", start=self.today.replace(year=year, month=12, day=20),
                                      end=self.today.replace(year=year + 1, month=1, day=20))
        self.assertEqual(self.pins(season="spring"), {spring.id})   # southern hemisphere box
        self.assertEqual(self.pins(season="summer"), {summer_wrap.id})

    def test_near_filter(self):
        close = make_submission(status="approved", lat=-37.81, lng=144.96)
        make_submission(status="approved", lat=-37.6, lng=145.4)
        self.assertEqual(self.pins(near="-37.81,144.96", radius_km=5), {close.id})

    def test_bad_params(self):
        for params in ({}, {"bbox": "1,2,3"}, {"bbox": "145,-37,144,-38"}, {"bbox": BBOX, "season": "monsoon"}):
            self.assertEqual(self.client.get("/api/v1/map/pins", params).status_code, 400, params)
