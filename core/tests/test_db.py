from io import StringIO

from django.core.management import call_command
from django.db import connection
from django.test import TestCase

from core.db import lock_down_tables, unlocked_tables


class RowLevelSecurityTests(TestCase):
    def rls_on(self, table):
        with connection.cursor() as cur:
            cur.execute("SELECT relrowsecurity FROM pg_class WHERE oid = %s::regclass", [table])
            return cur.fetchone()[0]

    def test_migrate_switches_rls_on_for_our_tables(self):
        # The test database was built by migrate, so post_migrate has already run
        for table in ("users_user", "plants_plant", "submissions_submission", "moderation_review", "django_migrations"):
            self.assertTrue(self.rls_on(table), table)
        self.assertEqual(unlocked_tables(), [])

    def test_extension_tables_are_left_alone(self):
        # PostGIS owns spatial_ref_sys; altering it would fail on Supabase
        self.assertFalse(self.rls_on("spatial_ref_sys"))

    def test_lock_down_is_idempotent_and_catches_new_tables(self):
        with connection.cursor() as cur:
            cur.execute("CREATE TABLE rls_probe (id int)")
        self.assertEqual(lock_down_tables(), ["rls_probe"])
        self.assertEqual(lock_down_tables(), [])
        self.assertTrue(self.rls_on("rls_probe"))


class CheckDbCommandTests(TestCase):
    def test_reports_healthy_local_database(self):
        out = StringIO()
        call_command("check_db", stdout=out)
        text = out.getvalue()
        self.assertIn("PostGIS", text)
        self.assertIn("RLS", text)
        self.assertIn("Database looks good", text)
        self.assertNotIn("bloom:bloom", text)   # never print the password
