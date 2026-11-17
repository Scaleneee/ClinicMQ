"""
queueing/services.py
Business logic for the Queue Ticket module. Views call these functions; keep views thin.

Queue rules (DESC.md §5):
  R1  Numbers reset daily, starting at 001 and going up by 1
  R2  Online and walk-in share one queue
  R3  1 active ticket per patient per day
  R4  Online numbers only during an open session; they stop 30 min before it ends
  R5  Only checked-in patients can be called
  R6  Call the checked-in patient with the smallest position
  R7  Skipped: a bigger number is called before you arrive; on check-in you go after
      the next 3 checked-in patients
  R8  Missed: called but no show within 3 min; rejoin once using R7; a 2nd miss cancels
  R9  Unfinished tickets expire at the end of each session
  R10 Numbers are generated inside a transaction, never duplicated
  R11 Tie-break: same position -> earlier check-in goes first
  R12 One room, one doctor: only one patient is called at a time

Errors: ValidationError (message for the user) and PermissionDenied (wrong role).
Every function that depends on the time takes an optional `now` so it can be tested.
"""

import datetime as dt

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Max
from django.utils import timezone

from accounts.models import Session
from accounts.services import doctor_on_duty

from .models import ClinicSetting, QueueTicket

Status = QueueTicket.Status

# Tickets still in play today. MISSED is included: it can rejoin once (R8).
OPEN_STATUSES = (
    Status.WAITING, Status.CHECKED_IN, Status.SKIPPED,
    Status.CALLED, Status.IN_CONSULTATION, Status.MISSED,
)
SERVING_STATUSES = (Status.CALLED, Status.IN_CONSULTATION)

QUEUE_STAFF = {"NURSE", "DOCTOR", "ADMIN"}  # run the queue (call, start, complete, no show)
DESK_STAFF = {"NURSE", "ADMIN"}             # issue walk-ins, check in or cancel any ticket


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def _local_now(now=None):
    return timezone.localtime(now)


def _fmt_time(t):
    """09:00 -> '9:00 AM'"""
    return t.strftime("%I:%M %p").lstrip("0")


def _require_role(user, roles, message):
    if not user.is_authenticated or user.role not in roles:
        raise PermissionDenied(message)


def _is_ticket_owner(user, ticket):
    return user.is_authenticated and user.role == "PATIENT" and ticket.patient.user_id == user.id


def _lock_queue():
    """Lock the single ClinicSetting row so only one queue change runs at a time (R10).

    Returns the settings. Must be called inside transaction.atomic().
    """
    ClinicSetting.load()  # make sure the row exists
    return ClinicSetting.objects.select_for_update().get(pk=1)


def _get_ticket_for_update(ticket_id):
    try:
        return QueueTicket.objects.select_for_update().get(pk=ticket_id)
    except QueueTicket.DoesNotExist:
        raise ValidationError("Queue ticket not found.")


# ---------------------------------------------------------------------------
# Sessions (times come from ClinicSetting)
# ---------------------------------------------------------------------------
def session_hours(session, setting=None):
    """(start, end) times of a session."""
    setting = setting or ClinicSetting.load()
    if session == Session.MORNING:
        return setting.morning_start, setting.morning_end
    return setting.night_start, setting.night_end


def current_session(now=None, setting=None):
    """'MORNING' or 'NIGHT' if a session is open now, else None."""
    setting = setting or ClinicSetting.load()
    t = _local_now(now).time()
    for session in (Session.MORNING, Session.NIGHT):
        start, end = session_hours(session, setting)
        if start <= t < end:
            return session
    return None


def session_end(date, session, setting=None):
    """When a session ends, as an aware datetime."""
    _, end = session_hours(session, setting)
    return timezone.make_aware(dt.datetime.combine(date, end))


def online_cutoff(date, session, setting=None):
    """Last moment to take an ONLINE number for a session (R4)."""
    setting = setting or ClinicSetting.load()
    return session_end(date, session, setting) - dt.timedelta(minutes=setting.online_cutoff_min)


def closed_message(setting=None):
    setting = setting or ClinicSetting.load()
    m_start, m_end = session_hours(Session.MORNING, setting)
    n_start, n_end = session_hours(Session.NIGHT, setting)
    return (
        "The clinic is closed now. Sessions: "
        f"{_fmt_time(m_start)} – {_fmt_time(m_end)} and {_fmt_time(n_start)} – {_fmt_time(n_end)}."
    )


# ---------------------------------------------------------------------------
# Create: take a number (online) or issue a walk-in number (nurse)
# ---------------------------------------------------------------------------
@transaction.atomic
def issue_ticket(*, issued_by, patient, source, now=None) -> QueueTicket:
    """Give `patient` the next queue number for the current session.

    source ONLINE: the patient takes it themself; status WAITING (not arrived yet).
    source WALKIN: a nurse/admin issues it at the counter; status CHECKED_IN straight away.

    Raises:
        PermissionDenied - wrong user for this source
        ValidationError  - clinic closed, online cut-off passed, no doctor on duty,
                           or the patient already has a ticket today (R3)
    """
    now = _local_now(now)
    today = now.date()

    # Who may issue it
    if source == QueueTicket.Source.ONLINE:
        if not (issued_by.is_authenticated and issued_by.role == "PATIENT"
                and patient.user_id == issued_by.id):
            raise PermissionDenied("You can only take a number for yourself.")
    elif source == QueueTicket.Source.WALKIN:
        _require_role(issued_by, DESK_STAFF, "Only nurses or admins can issue walk-in numbers.")
    else:
        raise ValidationError("Unknown ticket source.")

    setting = _lock_queue()  # from here on, one issuer at a time (R10)

    # Session open? (R4)
    session = current_session(now, setting)
    if session is None:
        raise ValidationError(closed_message(setting))
    if source == QueueTicket.Source.ONLINE:
        cutoff = online_cutoff(today, session, setting)
        if now >= cutoff:
            raise ValidationError(
                f"Online numbers for the {session.lower()} session closed at "
                f"{_fmt_time(timezone.localtime(cutoff).time())}. Please come to the counter."
            )

    # Doctor on duty?
    doctor = doctor_on_duty(today, session)
    if doctor is None:
        raise ValidationError("No doctor is on duty this session, so queue numbers can't be issued.")

    # One active ticket per patient per day (R3)
    if QueueTicket.objects.filter(patient=patient, queue_date=today, status__in=OPEN_STATUSES).exists():
        raise ValidationError("This patient already has a queue number today.")

    # Next number for today, shared by both sessions and both sources (R1, R2)
    last_no = QueueTicket.objects.filter(queue_date=today).aggregate(m=Max("queue_no"))["m"] or 0
    queue_no = last_no + 1

    walk_in = source == QueueTicket.Source.WALKIN
    try:
        return QueueTicket.objects.create(
            queue_date=today,
            queue_no=queue_no,
            position=queue_no,  # starts at its own number; moves only for late check-ins (R7)
            patient=patient,
            doctor=doctor,
            session=session,
            source=source,
            status=Status.CHECKED_IN if walk_in else Status.WAITING,
            checked_in_at=now if walk_in else None,
        )
    except IntegrityError:
        # Unique (queue_date, queue_no) is the safety net behind the lock.
        raise ValidationError("Someone took a number at the same moment. Please try again.")


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------
def get_todays_ticket(patient):
    """The patient's active ticket for today, or None.

    Active = not finished yet (WAITING, CHECKED_IN, SKIPPED, CALLED, IN_CONSULTATION).
    R3 allows at most one, so this returns the latest just in case.
    """
    if patient is None:
        return None
    return (
        QueueTicket.objects.today()
        .active()
        .filter(patient=patient)
        .select_related("doctor")
        .order_by("-issued_at")
        .first()
    )


def people_ahead(ticket):
    """How many patients will be called before this ticket.

    TODO (queue logic): count today's tickets in the same session that will be
    called first: CHECKED_IN tickets ordered by (position, checked_in_at), R6/R11.
    Returns None until implemented, and the page shows "–".
    """
    return None
