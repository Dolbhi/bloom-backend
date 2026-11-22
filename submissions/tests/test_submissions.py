from datetime import date

from rest_framework.test import APITestCase

from core.tests.factories import TempMediaMixin, make_moderator, make_plant, make_submission, make_user
from plants.models import Plant
from submissions.models import Submission


class UploadTests(TempMediaMixin, APITestCase):
    def setUp(self):
        self.user = make_user()
        self.client.force_authenticate(self.user)

    def test_presign_then_put(self):
        res = self.client.post("/api/v1/uploads/presign", {"content_type": "image/jpeg", "size_bytes": 1000})
        self.assertEqual(res.status_code, 200, res.data)
        self.assertTrue(res.data["photo_key"].startswith(f"submissions/{self.user.id}/"))
        self.assertEqual(res.data["method"], "PUT")
        put = self.client.generic("PUT", res.data["upload_url"], b"\xff\xd8\xffdata", content_type="image/jpeg")
        self.assertEqual(put.status_code, 200)
        photo = self.client.get(f"/media/{res.data['photo_key']}")
        self.assertEqual(photo.status_code, 200)

    def test_put_with_bad_token_is_403(self):
        put = self.client.generic("PUT", "/api/v1/uploads/local/forged", b"x", content_type="image/jpeg")
        self.assertEqual(put.status_code, 403)

    def test_presign_validation(self):
        self.assertEqual(self.client.post("/api/v1/uploads/presign", {"content_type": "image/gif", "size_bytes": 10}).status_code, 400)
        self.assertEqual(self.client.post("/api/v1/uploads/presign", {"content_type": "image/png", "size_bytes": 50 * 1024 * 1024}).status_code, 400)

    def test_presign_needs_login(self):
        self.client.force_authenticate(None)
        self.assertEqual(self.client.post("/api/v1/uploads/presign", {"content_type": "image/png", "size_bytes": 10}).status_code, 401)


class CreateSubmissionTests(TempMediaMixin, APITestCase):
    def setUp(self):
        self.user = make_user()
        self.plant = make_plant()
        self.client.force_authenticate(self.user)
        self.key = self.put_photo(f"submissions/{self.user.id}/2026/11/abc.jpg")

    def body(self, **over):
        data = {"plant_id": self.plant.id, "photo_key": self.key, "lat": -37.88, "lng": 145.06,
                "bloom_start": "2026-08-01", "bloom_end": "2026-09-30", "description": "By the station"}
        data.update(over)
        return {k: v for k, v in data.items() if v is not None}

    def test_create_with_existing_plant(self):
        res = self.client.post("/api/v1/submissions", self.body())
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(res.data["status"], "pending")
        self.assertEqual(res.data["revision"], 1)
        s = Submission.objects.get(pk=res.data["id"])
        self.assertEqual(s.user, self.user)
        self.assertAlmostEqual(s.location.x, 145.06)   # longitude first
        self.assertAlmostEqual(s.location.y, -37.88)

    def test_create_with_new_plant_name(self):
        res = self.client.post("/api/v1/submissions", self.body(plant_id=None, new_plant_name="Purple tree on Neerim Rd"))
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(res.data["plant"]["status"], "pending")
        plant = Plant.objects.get(pk=res.data["plant"]["id"])
        self.assertEqual(plant.created_by, self.user)

    def test_validation_errors(self):
        cases = [
            (self.body(new_plant_name="Also this"), "plant_id"),
            (self.body(plant_id=None), "plant_id"),
            (self.body(bloom_end="2026-07-01"), "bloom_end"),
            (self.body(bloom_end="2028-01-01"), "bloom_end"),
            (self.body(lat=91), "lat"),
            (self.body(photo_key=f"submissions/{self.user.id}/2026/11/missing.jpg"), "photo_key"),
            (self.body(photo_key="submissions/99999/2026/11/abc.jpg"), "photo_key"),
            (self.body(plant_id=999999), "plant_id"),
        ]
        for body, field in cases:
            res = self.client.post("/api/v1/submissions", body)
            self.assertEqual(res.status_code, 400, (body, res.data))
            self.assertIn(field, res.data)

    def test_cannot_use_someone_elses_pending_plant(self):
        other_plant = make_plant("Secret", status="pending", created_by=make_user())
        res = self.client.post("/api/v1/submissions", self.body(plant_id=other_plant.id))
        self.assertEqual(res.status_code, 400)

    def test_requires_login(self):
        self.client.force_authenticate(None)
        self.assertEqual(self.client.post("/api/v1/submissions", self.body()).status_code, 401)


class VisibilityTests(APITestCase):
    def test_pending_only_for_owner_and_moderators(self):
        owner = make_user()
        s = make_submission(user=owner)
        url = f"/api/v1/submissions/{s.id}"
        self.assertEqual(self.client.get(url).status_code, 404)
        self.client.force_authenticate(make_user())
        self.assertEqual(self.client.get(url).status_code, 404)
        self.client.force_authenticate(owner)
        self.assertEqual(self.client.get(url).status_code, 200)
        self.client.force_authenticate(make_moderator())
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_approved_is_public(self):
        s = make_submission(status="approved")
        res = self.client.get(f"/api/v1/submissions/{s.id}")
        self.assertEqual(res.status_code, 200)
        self.assertIsNone(res.data["latest_review"])


class ResubmitTests(TempMediaMixin, APITestCase):
    def setUp(self):
        self.owner = make_user()
        self.sub = make_submission(user=self.owner, status="changes_requested")
        self.url = f"/api/v1/submissions/{self.sub.id}"

    def test_owner_resubmits(self):
        self.client.force_authenticate(self.owner)
        key = self.put_photo(f"submissions/{self.owner.id}/2026/11/new.jpg")
        res = self.client.patch(self.url, {"photo_key": key, "description": "Retook the photo"})
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data["status"], "pending")
        self.assertEqual(res.data["revision"], 2)

    def test_only_while_changes_requested(self):
        self.sub.status = "pending"
        self.sub.save()
        self.client.force_authenticate(self.owner)
        self.assertEqual(self.client.patch(self.url, {"description": "x"}).status_code, 409)

    def test_not_owner(self):
        approved = make_submission(status="approved")
        self.client.force_authenticate(make_user())
        self.assertEqual(self.client.patch(f"/api/v1/submissions/{approved.id}", {"description": "x"}).status_code, 403)
        self.assertEqual(self.client.patch(self.url, {"description": "x"}).status_code, 404)

    def test_date_check_uses_existing_values(self):
        self.client.force_authenticate(self.owner)
        res = self.client.patch(self.url, {"bloom_end": str(date(2000, 1, 1))})
        self.assertEqual(res.status_code, 400)
        self.assertIn("bloom_end", res.data)
