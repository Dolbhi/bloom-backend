from django.apps import AppConfig
from django.conf import settings
from django.db.models.signals import post_migrate


def _lock_down_after_migrate(sender, using="default", verbosity=1, **kwargs):
    from core.db import lock_down_tables

    changed = lock_down_tables(using)
    if changed and verbosity >= 1:
        print(f"  Row Level Security switched on for {len(changed)} table(s).")


class CoreConfig(AppConfig):
    """Shared code used by every app: choices, permissions, storage, bloom maths. No models."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "core"

    def ready(self):
        if settings.DATABASE_ENABLE_RLS:
            # sender=self: run once per migrate (post_migrate fires after ALL migrations have run)
            post_migrate.connect(_lock_down_after_migrate, sender=self, dispatch_uid="core.lock_down_tables")
