from django.apps import AppConfig


class CoreConfig(AppConfig):
    """Shared code used by every app: choices, permissions, storage, bloom maths. No models."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "core"
