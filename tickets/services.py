"""All business rules live here so views stay thin and rules are testable."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from .models import (ACTIVE, ALLOWED, ASSIGNED, CLOSED, IN_PROGRESS, OPEN, PENDING,
                     PRIORITY_ORDER, RESOLVED, RUNNING, SLA_FACTOR, Ticket, TicketActivity)

User = get_user_model()
ESCALATION_L2_HOURS = 24   # breached for this long -> manager alert

# Moves a student may make on their own ticket
STUDENT_MOVES = {(RESOLVED, IN_PROGRESS), (RESOLVED, CLOSED)}


def in_group(user, name):
    return user.is_authenticated and user.groups.filter(name=name).exists()

def is_manager(user):
    return user.is_authenticated and (user.is_superuser or in_group(user, "Manager"))

def is_support(user):
    return is_manager(user) or in_group(user, "Staff")

def support_users():
    return User.objects.filter(groups__name__in=["Staff", "Manager"], is_active=True).distinct()


def log(ticket, actor, action, note="", internal=False):
    return TicketActivity.objects.create(ticket=ticket, actor=actor, action=action,
                                         note=note, is_internal=internal)


def compute_due(start, category, priority):
    return start + timedelta(hours=category.sla_hours * SLA_FACTOR[priority])


def auto_assign(ticket):
    """Give the ticket to the Staff member with the fewest active tickets (load balancing)."""
    staff = (User.objects.filter(groups__name="Staff", is_active=True)
             .annotate(load=Count("assigned_tickets", distinct=True,
                                  filter=Q(assigned_tickets__status__in=ACTIVE)))
             .order_by("load", "id").first())
    if staff:
        ticket.assigned_to = staff
        ticket.status = ASSIGNED
        ticket.save()
        log(ticket, None, "Auto-assigned", f"Assigned to {staff.username} (lowest current load)")


@transaction.atomic
def create_ticket(student, category, title, description):
    now = timezone.now()
    ticket = Ticket.objects.create(
        title=title, description=description, category=category, student=student,
        priority=category.default_priority, due_at=compute_due(now, category, category.default_priority))
    log(ticket, student, "Ticket created", f"Category: {category.name}, SLA due {ticket.due_at:%d %b %H:%M}")
    auto_assign(ticket)
    return ticket


@transaction.atomic
def change_status(ticket, actor, new_status, note=""):
    old = ticket.status
    if new_status not in ALLOWED[old]:
        raise ValueError(f"Cannot move ticket from {old} to {new_status}.")
    now = timezone.now()
    if old == PENDING and ticket.pending_since:
        # SLA clock was paused while waiting for the student: give that time back.
        ticket.due_at += now - ticket.pending_since
        ticket.pending_since = None
    if new_status == PENDING:
        ticket.pending_since = now
    if new_status == RESOLVED:
        ticket.resolved_at = now
    if old == RESOLVED and new_status == IN_PROGRESS:
        ticket.resolved_at = None
        ticket.reopen_count += 1
    if old == RESOLVED and new_status == CLOSED and not ticket.resolved_at:
        ticket.resolved_at = now
    ticket.status = new_status
    ticket.save()
    action = "Ticket reopened" if (old == RESOLVED and new_status == IN_PROGRESS) else f"Status: {old} -> {new_status}"
    log(ticket, actor, action, note)


@transaction.atomic
def assign(ticket, actor, user):
    old = ticket.assigned_to
    ticket.assigned_to = user
    if ticket.status == OPEN and user:
        ticket.status = ASSIGNED
    ticket.save()
    log(ticket, actor, "Assigned" if not old else "Reassigned",
        f"{old.username if old else 'nobody'} -> {user.username if user else 'nobody'}")


@transaction.atomic
def set_priority(ticket, actor, new_priority):
    old = ticket.priority
    if old == new_priority:
        return
    diff = SLA_FACTOR[new_priority] - SLA_FACTOR[old]
    ticket.due_at += timedelta(hours=ticket.category.sla_hours * diff)   # deadline follows priority
    ticket.priority = new_priority
    ticket.save()
    log(ticket, actor, "Priority changed", f"{old} -> {new_priority}; SLA due now {ticket.due_at:%d %b %H:%M}")


@transaction.atomic
def add_comment(ticket, actor, text, internal=False):
    log(ticket, actor, "Internal note" if internal else "Comment", text, internal=internal)
    ticket.save()  # bump updated_at
    # A student reply on a pending ticket resumes work and restarts the SLA clock.
    if ticket.status == PENDING and actor.id == ticket.student_id and not internal:
        change_status(ticket, actor, IN_PROGRESS, "Student replied")


@transaction.atomic
def run_escalation():
    """Escalate breached tickets. Safe to run repeatedly (idempotent per level)."""
    now = timezone.now()
    count = 0
    for t in Ticket.objects.filter(status__in=RUNNING, due_at__lt=now):
        if t.escalation_level == 0:
            idx = PRIORITY_ORDER.index(t.priority)
            if idx < len(PRIORITY_ORDER) - 1:
                t.priority = PRIORITY_ORDER[idx + 1]
            t.escalation_level = 1
            t.save()
            log(t, None, "Auto-escalated (level 1)", f"SLA breached; priority raised to {t.priority}")
            count += 1
        if t.escalation_level == 1 and now - t.due_at >= timedelta(hours=ESCALATION_L2_HOURS):
            t.priority = "URGENT"
            t.escalation_level = 2
            t.save()
            log(t, None, "Escalated to manager (level 2)",
                f"Breached for over {ESCALATION_L2_HOURS}h, marked URGENT", internal=True)
            count += 1
    return count
