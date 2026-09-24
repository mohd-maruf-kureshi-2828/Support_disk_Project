# Student Support & Ticket Management (Assignment 4)

Django + SQLite web app where students raise administrative requests (fees, attendance, ID card,
documents, certificates, other) and staff own, prioritise, process and resolve them, with SLA tracking,
auto-escalation, activity history and a manager dashboard.

## Run it
```bash
python -m venv venv
venv\Scripts\activate          # Windows   (Mac/Linux: source venv/bin/activate)
pip install -r requirements.txt
python manage.py makemigrations tickets
python manage.py migrate
python manage.py seed_demo      # demo categories, users, tickets
python manage.py runserver
```
Open http://127.0.0.1:8000

| Role | Login |
|---|---|
| Manager | manager / manager123 |
| Staff | staff1 / staff123, staff2 / staff123 |
| Student | student1 / student123, student2 / student123 (or sign up) |

Escalation runs automatically when a manager opens the dashboard, and can also be scheduled:
`python manage.py check_sla` (cron / Task Scheduler every 10-15 min).

## Roles
- **Student** (default for signup): create tickets, see only own tickets, comment, reopen or close a resolved ticket.
- **Staff** (group `Staff`): see all tickets, filter/search, change status, reassign, change priority, add internal notes.
- **Manager** (group `Manager`): everything above plus the dashboard.

## Workflow
`Open -> Assigned -> In Progress -> Pending (student action) -> Resolved -> Closed`
Allowed transitions are defined in one table (`ALLOWED` in `models.py`) and enforced in `services.change_status`,
so invalid jumps (e.g. Closed -> Open) are rejected.

## Key decisions
- **Business logic in `services.py`**, views stay thin. Every state change writes a `TicketActivity` row (audit trail).
- **SLA** = category base hours x priority factor (Urgent 0.5, High 0.75, Medium 1, Low 1.5). `due_at` is stored on the ticket.
- **SLA pause**: while status is *Pending (student action)* the clock is paused; when work resumes, `due_at` is pushed forward by the waiting time.
- **Auto-assignment**: new ticket goes to the Staff member with the fewest active tickets. If no staff exist it stays Open (unassigned).
- **Escalation** (idempotent): SLA breached -> level 1 (priority raised one step); breached for 24h+ -> level 2 (URGENT + internal note for manager). 
- **Ageing**: shown as time since creation on every list and on the dashboard's "oldest active tickets".
- **Internal notes** are hidden from students.

## Assumptions
- Students are self-registered accounts; staff/managers are created by admin (`/admin`) by adding users to groups.
- SLA is counted in wall-clock hours (no working-hours/holiday calendar).
- No email/SMS notifications (would be the next step); escalations are visible in the UI and history.

## Edge cases handled
- Invalid status transitions rejected; students can only perform reopen/close on their own resolved tickets.
- Students cannot open other students' tickets (404).
- Reopening a resolved ticket clears resolution time and increments the reopen counter.
- Priority change recalculates the deadline; escalation does not extend it.
- Student reply on a pending ticket automatically resumes it.
- Reassigning logs old and new owner; unassigned tickets are filterable and counted on the dashboard.
- Running escalation multiple times never double-escalates the same level.

## Trade-offs / next steps
- SQLite and server-rendered templates for speed of delivery; production would use PostgreSQL and a task queue (Celery) for escalation and notifications.
- Duplicate-ticket detection, file attachments, email notifications, working-hours SLA and automated tests are future work.

## Structure
```
config/            settings and urls
tickets/models.py  Category, Ticket, TicketActivity + status/priority rules
tickets/services.py business rules (create, assign, status, SLA, escalation)
tickets/views.py   list/filter, create, detail actions, dashboard
tickets/management/commands/  seed_demo, check_sla
```
