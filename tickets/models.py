from django.conf import settings
from django.db import models
from django.utils import timezone
from datetime import timedelta

PRIORITIES = [("LOW", "Low"), ("MEDIUM", "Medium"), ("HIGH", "High"), ("URGENT", "Urgent")]
PRIORITY_ORDER = ["LOW", "MEDIUM", "HIGH", "URGENT"]
# Urgent tickets get a shorter deadline, low priority a longer one.
SLA_FACTOR = {"URGENT": 0.5, "HIGH": 0.75, "MEDIUM": 1.0, "LOW": 1.5}

OPEN, ASSIGNED, IN_PROGRESS, PENDING, RESOLVED, CLOSED = (
    "OPEN", "ASSIGNED", "IN_PROGRESS", "PENDING_STUDENT", "RESOLVED", "CLOSED")
STATUSES = [
    (OPEN, "Open"), (ASSIGNED, "Assigned"), (IN_PROGRESS, "In Progress"),
    (PENDING, "Pending (student action)"), (RESOLVED, "Resolved"), (CLOSED, "Closed"),
]
ACTIVE = [OPEN, ASSIGNED, IN_PROGRESS, PENDING]      # not finished yet
RUNNING = [OPEN, ASSIGNED, IN_PROGRESS]              # SLA clock is running
ALLOWED = {                                          # allowed status transitions
    OPEN: [ASSIGNED, IN_PROGRESS, CLOSED],
    ASSIGNED: [OPEN, IN_PROGRESS, PENDING, RESOLVED],
    IN_PROGRESS: [PENDING, RESOLVED],
    PENDING: [IN_PROGRESS, RESOLVED],
    RESOLVED: [IN_PROGRESS, CLOSED],                 # IN_PROGRESS here = reopen
    CLOSED: [],
}


class Category(models.Model):
    name = models.CharField(max_length=60, unique=True)
    sla_hours = models.PositiveIntegerField(default=48, help_text="Base SLA in hours")
    default_priority = models.CharField(max_length=10, choices=PRIORITIES, default="MEDIUM")

    class Meta:
        verbose_name_plural = "categories"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Ticket(models.Model):
    title = models.CharField(max_length=200)
    description = models.TextField()
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="tickets")
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="tickets")
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name="assigned_tickets")
    status = models.CharField(max_length=20, choices=STATUSES, default=OPEN, db_index=True)
    priority = models.CharField(max_length=10, choices=PRIORITIES, default="MEDIUM", db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    due_at = models.DateTimeField()
    resolved_at = models.DateTimeField(null=True, blank=True)
    pending_since = models.DateTimeField(null=True, blank=True)  # SLA paused while waiting on student
    escalation_level = models.PositiveSmallIntegerField(default=0)  # 0 none, 1 priority bumped, 2 manager alerted
    reopen_count = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.reference} {self.title}"

    @property
    def reference(self):
        return f"TKT-{self.pk:05d}" if self.pk else "TKT-NEW"

    def allowed_next(self):
        labels = dict(STATUSES)
        return [(s, labels[s]) for s in ALLOWED[self.status]]

    @property
    def sla_state(self):
        now = timezone.now()
        if self.status in (RESOLVED, CLOSED):
            if self.resolved_at:
                return "met" if self.resolved_at <= self.due_at else "breached late"
            return "closed"
        if self.status == PENDING:
            return "paused"
        if now > self.due_at:
            return "breached"
        if self.due_at - now < timedelta(hours=4):
            return "at risk"
        return "on track"


class TicketActivity(models.Model):
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="activities")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    action = models.CharField(max_length=80)
    note = models.TextField(blank=True)
    is_internal = models.BooleanField(default=False)  # staff-only notes hidden from student
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.ticket_id}: {self.action}"
