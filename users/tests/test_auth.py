from django.core.cache import cache
from rest_framework.test import APITestCase

from core.tests.factories import make_submission, make_user

PASSWORD = "correct-horse-battery-9"


class SignupLoginTests(APITestCase):
    def setUp(self):
        cache.clear()   # reset the auth throttle between tests

    def signup(self, email="bevan@example.com", password=PASSWORD):
        return self.client.post("/api/v1/auth/signup", {"email": email, "password": password, "display_name": "Bevan"})

    def test_signup_returns_user_and_tokens(self):
        res = self.signup()
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(res.data["user"]["email"], "bevan@example.com")
        self.assertEqual(res.data["user"]["reputation"], 0)
        self.assertFalse(res.data["user"]["can_moderate"])
        self.assertIn("access", res.data)
        self.assertIn("refresh", res.data)

    def test_email_is_case_insensitive(self):
        self.signup("Bevan@Example.com")
        self.assertEqual(self.signup("bevan@example.com").status_code, 409)
        res = self.client.post("/api/v1/auth/login", {"email": "BEVAN@example.com", "password": PASSWORD})
        self.assertEqual(res.status_code, 200)

    def test_weak_password_rejected(self):
        res = self.signup(password="123")
        self.assertEqual(res.status_code, 400)
        self.assertIn("password", res.data)

    def test_wrong_password_is_401(self):
        self.signup()
        res = self.client.post("/api/v1/auth/login", {"email": "bevan@example.com", "password": "nope-nope-nope"})
        self.assertEqual(res.status_code, 401)

    def test_trailing_slash_also_works(self):
        self.assertEqual(self.client.post("/api/v1/auth/signup/", {
            "email": "slash@example.com", "password": PASSWORD}).status_code, 201)

    def test_refresh_and_logout(self):
        tokens = self.signup().data
        res = self.client.post("/api/v1/auth/refresh", {"refresh": tokens["refresh"]})
        self.assertEqual(res.status_code, 200)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
        self.assertEqual(self.client.post("/api/v1/auth/logout", {"refresh": tokens["refresh"]}).status_code, 204)
        res = self.client.post("/api/v1/auth/refresh", {"refresh": tokens["refresh"]})
        self.assertEqual(res.status_code, 401)   # blacklisted


class MeTests(APITestCase):
    def test_requires_login(self):
        self.assertEqual(self.client.get("/api/v1/users/me").status_code, 401)

    def test_profile_lists_own_submissions(self):
        user = make_user()
        make_submission(user=user)
        make_submission()   # someone else's
        self.client.force_authenticate(user)
        res = self.client.get("/api/v1/users/me")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.data["submissions"]), 1)
        self.assertEqual(res.data["submissions"][0]["status"], "pending")
        self.assertIsNone(res.data["submissions"][0]["latest_review"])

    def test_change_display_name_only(self):
        user = make_user()
        self.client.force_authenticate(user)
        res = self.client.patch("/api/v1/users/me", {"display_name": "Bev", "reputation": 999, "role": "admin"})
        self.assertEqual(res.status_code, 200)
        user.refresh_from_db()
        self.assertEqual(user.display_name, "Bev")
        self.assertEqual(user.reputation, 0)
        self.assertEqual(user.role, "user")

    def test_reputation_threshold_unlocks_review(self):
        from django.conf import settings

        user = make_user(reputation=settings.BLOOM["MODERATOR_REPUTATION"])
        self.client.force_authenticate(user)
        self.assertTrue(self.client.get("/api/v1/users/me").data["can_moderate"])


class PublicProfileTests(APITestCase):
    def test_never_shows_email_or_pending(self):
        user = make_user()
        make_submission(user=user, status="approved")
        make_submission(user=user)   # pending
        res = self.client.get(f"/api/v1/users/{user.id}")
        self.assertEqual(res.status_code, 200)
        self.assertNotIn("email", res.data)
        self.assertEqual(res.data["submissions"]["count"], 1)
