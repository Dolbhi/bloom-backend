from django.conf import settings
from rest_framework.test import APITestCase

from core.tests.factories import make_moderator, make_plant, make_submission, make_user
from moderation.models import ReputationEvent, Review
from moderation.services import rebuild_reputation
from plants.models import PlantEdit

REP = settings.BLOOM


def decide(client, sub, decision, comment=""):
    return client.post(f"/api/v1/moderation/submissions/{sub.id}/decision", {"decision": decision, "comment": comment})


class PermissionTests(APITestCase):
    def test_normal_user_blocked(self):
        self.client.force_authenticate(make_user())
        self.assertEqual(self.client.get("/api/v1/moderation/queue").status_code, 403)

    def test_anonymous_blocked(self):
        self.assertEqual(self.client.get("/api/v1/moderation/queue").status_code, 401)

    def test_high_reputation_user_allowed(self):
        self.client.force_authenticate(make_user(reputation=REP["MODERATOR_REPUTATION"]))
        self.assertEqual(self.client.get("/api/v1/moderation/queue").status_code, 200)


class QueueTests(APITestCase):
    def test_oldest_first_without_own_items(self):
        mod = make_moderator()
        first = make_submission()
        second = make_submission()
        make_submission(user=mod)                     # own: hidden
        make_submission(status="approved")            # not pending
        edit = PlantEdit.objects.create(plant=make_plant(), user=make_user(), proposed_changes={"description": "x"})
        self.client.force_authenticate(mod)
        res = self.client.get("/api/v1/moderation/queue")
        self.assertEqual(res.status_code, 200)
        self.assertEqual([(i["type"], i["id"]) for i in res.data["results"]],
                         [("submission", first.id), ("submission", second.id), ("plant_edit", edit.id)])
        only_subs = self.client.get("/api/v1/moderation/queue", {"type": "submission"}).data["results"]
        self.assertEqual(len(only_subs), 2)

    def test_low_reputation_flag(self):
        make_submission(user=make_user(reputation=-20))
        self.client.force_authenticate(make_moderator())
        item = self.client.get("/api/v1/moderation/queue").data["results"][0]
        self.assertTrue(item["contributor"]["low_reputation"])


class DecisionTests(APITestCase):
    def setUp(self):
        self.mod = make_moderator()
        self.author = make_user()
        self.plant = make_plant("Purple tree", status="pending", created_by=self.author)
        self.sub = make_submission(user=self.author, plant=self.plant)
        self.client.force_authenticate(self.mod)

    def rep(self, user):
        user.refresh_from_db()
        return user.reputation

    def test_approve_is_one_complete_transaction(self):
        res = decide(self.client, self.sub, "approve")
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data["submission"]["status"], "approved")
        self.sub.refresh_from_db()
        self.plant.refresh_from_db()
        self.assertEqual(self.sub.status, "approved")
        self.assertEqual(self.plant.status, "approved")            # new plant goes public
        self.assertEqual(self.plant.hero_submission_id, self.sub.id)
        review = Review.objects.get()
        self.assertEqual(review.submission_revision, 1)
        self.assertEqual(self.rep(self.author), REP["REP_SUBMISSION_APPROVED"])
        self.assertEqual(self.rep(self.mod), REP["REP_REVIEW_COMPLETED"])
        self.assertEqual(ReputationEvent.objects.count(), 2)

    def test_request_changes_needs_comment(self):
        self.assertEqual(decide(self.client, self.sub, "request_changes").status_code, 400)
        res = decide(self.client, self.sub, "request_changes", "Photo is blurry")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(self.rep(self.author), 0)
        self.assertEqual(self.rep(self.mod), REP["REP_REVIEW_COMPLETED"])

    def test_reject_lowers_reputation(self):
        decide(self.client, self.sub, "reject")
        self.assertEqual(self.rep(self.author), REP["REP_SUBMISSION_REJECTED"])
        self.plant.refresh_from_db()
        self.assertEqual(self.plant.status, "pending")

    def test_second_decision_is_409_and_no_double_reputation(self):
        decide(self.client, self.sub, "approve")
        other_mod = make_moderator()
        self.client.force_authenticate(other_mod)
        self.assertEqual(decide(self.client, self.sub, "reject").status_code, 409)
        self.assertEqual(self.rep(self.author), REP["REP_SUBMISSION_APPROVED"])
        self.assertEqual(self.rep(other_mod), 0)
        self.assertEqual(Review.objects.count(), 1)

    def test_cannot_review_own(self):
        own = make_submission(user=self.mod)
        res = decide(self.client, own, "approve")
        self.assertEqual(res.status_code, 403)

    def test_invalid_decision(self):
        self.assertEqual(decide(self.client, self.sub, "maybe").status_code, 400)

    def test_resubmit_cycle_keeps_review_per_revision(self):
        decide(self.client, self.sub, "request_changes", "Retake please")
        self.sub.refresh_from_db()
        self.sub.status, self.sub.revision = "pending", 2
        self.sub.save()
        decide(self.client, self.sub, "approve")
        self.assertEqual(sorted(Review.objects.values_list("submission_revision", flat=True)), [1, 2])
        detail = self.client.get(f"/api/v1/moderation/submissions/{self.sub.id}").data
        self.assertEqual(len(detail["previous_reviews"]), 2)

    def test_owner_sees_reviewer_comment(self):
        decide(self.client, self.sub, "request_changes", "Photo is blurry")
        self.client.force_authenticate(self.author)
        me = self.client.get("/api/v1/users/me").data
        self.assertEqual(me["submissions"][0]["latest_review"]["comment"], "Photo is blurry")

    def test_rebuild_matches_cached_scores(self):
        decide(self.client, self.sub, "approve")
        type(self.author).objects.filter(pk=self.author.pk).update(reputation=999)
        self.assertEqual(rebuild_reputation(), 1)
        self.assertEqual(self.rep(self.author), REP["REP_SUBMISSION_APPROVED"])


class DuplicateTests(APITestCase):
    def test_nearby_same_plant_overlapping_dates(self):
        plant = make_plant()
        target = make_submission(plant=plant, lat=-37.8800, lng=145.0600)
        dup = make_submission(plant=plant, lat=-37.8803, lng=145.0602, status="approved")   # ~40 m away
        make_submission(plant=plant, lat=-37.90, lng=145.10, status="approved")             # km away
        self.client.force_authenticate(make_moderator())
        res = self.client.get(f"/api/v1/moderation/submissions/{target.id}")
        self.assertEqual([d["id"] for d in res.data["possible_duplicates"]], [dup.id])
        self.assertLess(res.data["possible_duplicates"][0]["metres_away"], 100)


class PlantEditDecisionTests(APITestCase):
    def test_approve_applies_changes(self):
        plant = make_plant("Golden Wattle")
        author = make_user()
        edit = PlantEdit.objects.create(plant=plant, user=author, proposed_changes={"scientific_name": "Acacia pycnantha"})
        self.client.force_authenticate(make_moderator())
        res = self.client.post(f"/api/v1/moderation/plant-edits/{edit.id}/decision", {"decision": "approve"})
        self.assertEqual(res.status_code, 200, res.data)
        plant.refresh_from_db()
        author.refresh_from_db()
        self.assertEqual(plant.scientific_name, "Acacia pycnantha")
        self.assertEqual(author.reputation, REP["REP_EDIT_APPROVED"])

    def test_duplicate_scientific_name_is_409(self):
        make_plant("A", "Acacia pycnantha")
        plant = make_plant("B")
        edit = PlantEdit.objects.create(plant=plant, user=make_user(), proposed_changes={"scientific_name": "acacia PYCNANTHA"})
        self.client.force_authenticate(make_moderator())
        res = self.client.post(f"/api/v1/moderation/plant-edits/{edit.id}/decision", {"decision": "approve"})
        self.assertEqual(res.status_code, 409)
        edit.refresh_from_db()
        self.assertEqual(edit.status, "pending")   # rolled back
