from django.core.management.base import BaseCommand

from moderation.services import rebuild_reputation


class Command(BaseCommand):
    help = "Recalculate every user's reputation from the reputation_event log."

    def handle(self, *args, **opts):
        changed = rebuild_reputation()
        self.stdout.write(self.style.SUCCESS(f"Done. {changed} user(s) corrected."))
