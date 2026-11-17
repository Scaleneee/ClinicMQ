"""
queueing/views.py
Queue Ticket screens (UI.md §5.3). Views stay thin: they call queueing/services.py
and turn its ValidationError / PermissionDenied into messages.

Every queue page (and its 5-second live refresh) runs q.run_housekeeping() first,
so no-shows (R8) and session expiry (R9) happen without a background job.
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from accounts.decorators import role_required

from . import services as q
from .models import ClinicSetting, QueueTicket

Status = QueueTicket.Status
CANCELLABLE = [s for s in q.OPEN_STATUSES if s != Status.IN_CONSULTATION]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _patient_of(user):
    try:
        return user.patient
    except ObjectDoesNotExist:
        return None


def _run(request, action, success=None):
    """Call a service; show its error as a message. Returns the result, or None on error."""
    try:
        result = action()
    except ValidationError as e:
        messages.error(request, " ".join(e.messages))
        return None
    except PermissionDenied as e:
        messages.error(request, str(e) or "You don't have permission to do that.")
        return None
    if success:
        messages.success(request, success(result) if callable(success) else success)
    return result


def _ticket_context(ticket):
    """Everything the live ticket block needs."""
    return {
        "ticket": ticket,
        "s": q.live_status(ticket) if ticket else None,
        "cs": ClinicSetting.load(),
        "is_live": ticket is not None and ticket.status in q.OPEN_STATUSES,
        "can_cancel": ticket is not None and ticket.status in CANCELLABLE,
    }


# ---------------------------------------------------------------------------
# Patient: Get number, My queue, cancel
# ---------------------------------------------------------------------------
@role_required("PATIENT")
def get_number(request):
    q.run_housekeeping()
    patient = _patient_of(request.user)
    ticket = q.get_todays_ticket(patient)

    if request.method == "POST":
        if ticket:
            return redirect("queueing:my_queue")
        new = _run(
            request,
            lambda: q.issue_ticket(issued_by=request.user, patient=patient, source=QueueTicket.Source.ONLINE),
            lambda t: f"Your number is {t.queue_no:03d}. We'll show your place in line here.",
        )
        return redirect("queueing:my_queue" if new else "queueing:get_number")

    return render(request, "queueing/get_number.html", {
        "patient": patient,
        "ticket": ticket,
        "o": q.queue_overview(),
    })


@role_required("PATIENT")
def my_queue(request):
    q.run_housekeeping()
    ticket = q.latest_ticket_today(_patient_of(request.user))
    return render(request, "queueing/my_queue.html", _ticket_context(ticket))


@role_required("PATIENT")
def my_queue_live(request):
    """The part of My queue that refreshes every 5 seconds (HTMX)."""
    q.run_housekeeping()
    ticket = q.latest_ticket_today(_patient_of(request.user))
    return render(request, "queueing/_ticket_live.html", {**_ticket_context(ticket), "mode": "patient"})


@require_POST
@role_required("PATIENT")
def cancel_my_ticket(request):
    ticket = q.get_todays_ticket(_patient_of(request.user))
    if ticket:
        _run(request, lambda: q.cancel_ticket(cancelled_by=request.user, ticket_id=ticket.pk),
             f"Number {ticket.queue_no:03d} was cancelled.")
    return redirect("queueing:my_queue")


# ---------------------------------------------------------------------------
# Patient: check in by scanning the daily QR on the TV board
# ---------------------------------------------------------------------------
@login_required
def qr_check_in(request, code):
    q.run_housekeeping()
    valid = q.is_valid_checkin_code(code)
    patient = _patient_of(request.user) if request.user.role == "PATIENT" else None
    ticket = q.get_todays_ticket(patient)

    if request.method == "POST" and valid and ticket:
        _run(request, lambda: q.check_in(checked_in_by=request.user, ticket_id=ticket.pk))
        return redirect("queueing:qr_check_in", code=code)

    return render(request, "queueing/check_in.html", {
        "valid": valid,
        "is_patient": request.user.role == "PATIENT",
        "ticket": ticket,
        "s": q.live_status(ticket) if ticket else None,
        "can_check_in": ticket is not None and ticket.status in (Status.WAITING, Status.SKIPPED, Status.MISSED),
        "cs": ClinicSetting.load(),
    })


# ---------------------------------------------------------------------------
# Public: status page opened from the QR on a printed walk-in ticket (no login)
# ---------------------------------------------------------------------------
def ticket_status(request, token):
    q.run_housekeeping()
    ticket = get_object_or_404(QueueTicket, public_token=token)
    return render(request, "queueing/ticket_status.html", _ticket_context(ticket))


def ticket_status_live(request, token):
    q.run_housekeeping()
    ticket = get_object_or_404(QueueTicket, public_token=token)
    return render(request, "queueing/_ticket_live.html", {**_ticket_context(ticket), "mode": "public"})


# ---------------------------------------------------------------------------
# Nurse: Queue board
# ---------------------------------------------------------------------------
BOARD_FILTERS = [
    ("all", "All", None),
    ("not_arrived", "Not arrived", {Status.WAITING}),
    ("checked_in", "Checked in", {Status.CHECKED_IN}),
    ("called", "Called", {Status.CALLED}),
    ("with_doctor", "With doctor", {Status.IN_CONSULTATION}),
    ("skipped", "Skipped", {Status.SKIPPED}),
    ("missed", "Missed", {Status.MISSED}),
    ("completed", "Completed", {Status.COMPLETED}),
    ("cancelled", "Cancelled", {Status.CANCELLED, Status.EXPIRED}),
]
DESK_ROLES = ("NURSE", "ADMIN")
STAFF_ROLES = ("NURSE", "DOCTOR", "ADMIN")


def _board_context(request):
    o = q.queue_overview()
    tickets = q.board_tickets(o["date"], o["session"])
    key = request.GET.get("status") or request.POST.get("status") or "all"
    if key not in {k for k, _, _ in BOARD_FILTERS}:
        key = "all"

    pills, shown = [], tickets
    for k, label, statuses in BOARD_FILTERS:
        matching = tickets if statuses is None else [t for t in tickets if t.status in statuses]
        pills.append({"key": k, "label": label, "count": len(matching), "active": k == key})
        if k == key:
            shown = matching
    return {
        "o": o,
        "tickets": shown,
        "pills": pills,
        "status_key": key,
        "can_act": request.user.role in DESK_ROLES,
        "cancellable": CANCELLABLE,
    }


def _back_to_board(request):
    key = request.POST.get("status", "all")
    url = reverse("queueing:board")
    return redirect(f"{url}?status={key}" if key != "all" else url)


@role_required(*STAFF_ROLES)
def board(request):
    q.run_housekeeping()
    return render(request, "queueing/board.html", _board_context(request))


@role_required(*STAFF_ROLES)
def board_live(request):
    """The board table, refreshed every 10 seconds (HTMX)."""
    q.run_housekeeping()
    return render(request, "queueing/_board_table.html", _board_context(request))


@require_POST
@role_required(*DESK_ROLES)
def board_check_in(request, ticket_id):
    _run(request, lambda: q.check_in(checked_in_by=request.user, ticket_id=ticket_id),
         lambda t: f"Number {t.queue_no:03d} checked in.")
    return _back_to_board(request)


@require_POST
@role_required(*DESK_ROLES)
def board_cancel(request, ticket_id):
    _run(request, lambda: q.cancel_ticket(cancelled_by=request.user, ticket_id=ticket_id),
         lambda t: f"Number {t.queue_no:03d} cancelled.")
    return _back_to_board(request)


# ---------------------------------------------------------------------------
# Nurse: Walk-in (search patient -> issue number -> print ticket)
# ---------------------------------------------------------------------------
@role_required(*DESK_ROLES)
def walk_in(request):
    from patients.models import Patient
    from patients.services import search_patients

    q.run_housekeeping()

    if request.method == "POST":
        patient = get_object_or_404(Patient, pk=request.POST.get("patient"))
        ticket = _run(request, lambda: q.issue_ticket(
            issued_by=request.user, patient=patient, source=QueueTicket.Source.WALKIN))
        if ticket:
            return redirect("queueing:walkin_ticket", ticket_id=ticket.pk)
        return redirect(f"{reverse('queueing:walk_in')}?patient={patient.pk}")

    query = request.GET.get("q", "").strip()
    results = list(search_patients(searched_by=request.user, query=query)) if query else []
    selected = None
    if request.GET.get("patient", "").isdigit():
        selected = Patient.objects.filter(pk=request.GET["patient"]).first()

    return render(request, "queueing/walk_in.html", {
        "o": q.queue_overview(),
        "query": query,
        "results": results,
        "selected": selected,
        "existing": q.get_todays_ticket(selected) if selected else None,
    })


@role_required(*DESK_ROLES)
def walkin_ticket(request, ticket_id):
    """Issued number with a printable 80 mm ticket (number, people ahead, wait, QR). No name or IC."""
    ticket = get_object_or_404(QueueTicket, pk=ticket_id)
    status_url = request.build_absolute_uri(reverse("queueing:ticket_status", args=[ticket.public_token]))
    return render(request, "queueing/walkin_ticket.html", {
        "ticket": ticket,
        "s": q.live_status(ticket),
        "status_url": status_url,
        "cs": ClinicSetting.load(),
    })
