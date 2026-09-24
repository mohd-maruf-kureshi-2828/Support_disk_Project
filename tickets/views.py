from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.core.exceptions import PermissionDenied
from django.db.models import Count, F, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from . import services
from .forms import TicketForm
from .models import (ACTIVE, PENDING, PRIORITIES, RUNNING, STATUSES, Category, Ticket)


def signup(request):
    form = UserCreationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()          # new accounts are students (no group)
        login(request, user)
        return redirect("ticket_list")
    return render(request, "registration/signup.html", {"form": form})


@login_required
def ticket_list(request):
    qs = Ticket.objects.select_related("category", "student", "assigned_to")
    support = services.is_support(request.user)
    if not support:
        qs = qs.filter(student=request.user)
    else:
        g = request.GET
        if g.get("status"):
            qs = qs.filter(status=g["status"])
        if g.get("priority"):
            qs = qs.filter(priority=g["priority"])
        if g.get("category"):
            qs = qs.filter(category_id=g["category"])
        if g.get("mine"):
            qs = qs.filter(assigned_to=request.user)
        if g.get("unassigned"):
            qs = qs.filter(assigned_to__isnull=True, status__in=ACTIVE)
        if g.get("overdue"):
            qs = qs.filter(status__in=RUNNING, due_at__lt=timezone.now())
        if g.get("q"):
            qs = qs.filter(Q(title__icontains=g["q"]) | Q(student__username__icontains=g["q"]))
    return render(request, "tickets/list.html", {
        "tickets": qs, "statuses": STATUSES, "priorities": PRIORITIES,
        "categories": Category.objects.all(), "filters": request.GET,
    })


@login_required
def ticket_create(request):
    form = TicketForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        ticket = services.create_ticket(request.user, d["category"], d["title"], d["description"])
        messages.success(request, f"Ticket {ticket.reference} created.")
        return redirect("ticket_detail", pk=ticket.pk)
    return render(request, "tickets/create.html", {"form": form})


@login_required
def ticket_detail(request, pk):
    ticket = get_object_or_404(Ticket.objects.select_related("category", "student", "assigned_to"), pk=pk)
    support = services.is_support(request.user)
    if not support and ticket.student_id != request.user.id:
        raise Http404
    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if action == "comment":
                text = request.POST.get("text", "").strip()
                if text:
                    services.add_comment(ticket, request.user, text,
                                         internal=support and bool(request.POST.get("internal")))
            elif action == "status":
                new = request.POST.get("status")
                note = request.POST.get("note", "").strip()
                if not support and (ticket.status, new) not in services.STUDENT_MOVES:
                    raise PermissionDenied
                services.change_status(ticket, request.user, new, note)
            elif action == "assign" and support:
                uid = request.POST.get("assignee")
                user = services.support_users().filter(pk=uid).first() if uid else None
                services.assign(ticket, request.user, user)
            elif action == "priority" and support:
                services.set_priority(ticket, request.user, request.POST.get("priority"))
            else:
                raise PermissionDenied
        except ValueError as e:
            messages.error(request, str(e))
        except KeyError:
            messages.error(request, "Invalid value.")
        return redirect("ticket_detail", pk=pk)

    activities = ticket.activities.select_related("actor")
    nexts = ticket.allowed_next()
    if not support:
        activities = activities.filter(is_internal=False)
        nexts = [(v, l) for v, l in nexts if (ticket.status, v) in services.STUDENT_MOVES]
    return render(request, "tickets/detail.html", {
        "ticket": ticket, "activities": activities, "next_statuses": nexts,
        "assignees": services.support_users(), "priorities": PRIORITIES,
    })


@login_required
def dashboard(request):
    if not services.is_manager(request.user):
        raise PermissionDenied
    services.run_escalation()   # refresh SLA state whenever a manager opens the dashboard
    now = timezone.now()
    labels = dict(STATUSES)
    by_status = [(labels[r["status"]], r["n"]) for r in
                 Ticket.objects.values("status").annotate(n=Count("id")).order_by("status")]
    staff = (services.support_users().annotate(
        active=Count("assigned_tickets", distinct=True, filter=Q(assigned_tickets__status__in=ACTIVE)),
        overdue=Count("assigned_tickets", distinct=True,
                      filter=Q(assigned_tickets__status__in=RUNNING, assigned_tickets__due_at__lt=now)),
    ).order_by("-active"))
    resolved = Ticket.objects.filter(resolved_at__isnull=False)
    n_resolved = resolved.count()
    met = resolved.filter(resolved_at__lte=F("due_at")).count()
    spans = [(r - c).total_seconds() for c, r in resolved.values_list("created_at", "resolved_at")]
    ctx = {
        "total": Ticket.objects.count(),
        "active": Ticket.objects.filter(status__in=ACTIVE).count(),
        "overdue": Ticket.objects.filter(status__in=RUNNING, due_at__lt=now).count(),
        "escalated": Ticket.objects.filter(status__in=ACTIVE, escalation_level__gt=0).count(),
        "unassigned": Ticket.objects.filter(status__in=ACTIVE, assigned_to__isnull=True).count(),
        "by_status": by_status,
        "by_category": Category.objects.annotate(n=Count("tickets")).order_by("-n"),
        "staff": staff,
        "compliance": round(100 * met / n_resolved) if n_resolved else None,
        "avg_hours": round(sum(spans) / len(spans) / 3600, 1) if spans else None,
        "oldest": Ticket.objects.filter(status__in=ACTIVE).select_related("assigned_to", "category")
                        .order_by("created_at")[:5],
    }
    return render(request, "tickets/dashboard.html", ctx)
