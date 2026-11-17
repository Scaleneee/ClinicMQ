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
