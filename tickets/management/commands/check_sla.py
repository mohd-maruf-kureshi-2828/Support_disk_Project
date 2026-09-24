from django.core.management.base import BaseCommand
from tickets import services


class Command(BaseCommand):
    help = "Escalate tickets whose SLA has been breached (run via cron/Task Scheduler every few minutes)."

    def handle(self, *args, **opts):
        n = services.run_escalation()
        self.stdout.write(self.style.SUCCESS(f"{n} escalation(s) applied."))
