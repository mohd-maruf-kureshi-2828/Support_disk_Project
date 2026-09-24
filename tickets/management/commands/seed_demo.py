from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand
from django.utils import timezone

from tickets import services
from tickets.models import Category, Ticket

User = get_user_model()


class Command(BaseCommand):
    help = "Create demo categories, users and tickets."

    def handle(self, *args, **opts):
        cats = {}
        for name, hours, prio in [("Fees", 24, "HIGH"), ("Attendance", 48, "MEDIUM"), ("ID Card", 72, "LOW"),
                                  ("Documents", 72, "MEDIUM"), ("Certificates", 120, "LOW"), ("Other", 96, "LOW")]:
            cats[name], _ = Category.objects.get_or_create(
                name=name, defaults={"sla_hours": hours, "default_priority": prio})
        staff_g, _ = Group.objects.get_or_create(name="Staff")
        mgr_g, _ = Group.objects.get_or_create(name="Manager")

        def mk(username, pw, group=None):
            u, created = User.objects.get_or_create(username=username)
            if created:
                u.set_password(pw)
                u.save()
            if group:
                u.groups.add(group)
            return u

        mk("manager", "manager123", mgr_g)
        mk("staff1", "staff123", staff_g)
        mk("staff2", "staff123", staff_g)
        s1, s2 = mk("student1", "student123"), mk("student2", "student123")

        if Ticket.objects.exists():
            self.stdout.write("Tickets already exist, skipping sample tickets.")
            return
        a = services.create_ticket(s1, cats["Fees"], "Fee paid but not showing", "Paid 12,000 via UPI, receipt missing.")
        b = services.create_ticket(s1, cats["ID Card"], "Lost my ID card", "Need a duplicate ID card.")
        c = services.create_ticket(s2, cats["Certificates"], "Bonafide certificate", "Need it for a bank loan.")
        d = services.create_ticket(s2, cats["Attendance"], "Attendance mismatch in Maths", "Marked absent while present.")
        # Backdate one ticket so the SLA breach / escalation demo works immediately.
        now = timezone.now()
        Ticket.objects.filter(pk=a.pk).update(created_at=now - timedelta(hours=30), due_at=now - timedelta(hours=6))
        Ticket.objects.filter(pk=d.pk).update(created_at=now - timedelta(hours=60), due_at=now - timedelta(hours=30))
        self.stdout.write(self.style.SUCCESS("Demo data ready. Logins: manager/manager123, staff1/staff123, student1/student123"))
