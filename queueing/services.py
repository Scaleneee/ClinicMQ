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
from decimal import ROUND_DOWN, Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Max, Q
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

CENT = Decimal("0.01")  # position has 2 decimal places


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
# The line: checked-in tickets in calling order (R6, R11)
# ---------------------------------------------------------------------------
def waiting_line(date, session):
    """CHECKED_IN tickets in the order they will be called."""
    return QueueTicket.objects.filter(
        queue_date=date, session=session, status=Status.CHECKED_IN,
    ).order_by("position", "checked_in_at", "ticket_id")


def _was_moved(ticket):
    """True if a late check-in gave this ticket a new position (R7)."""
    return ticket.position != Decimal(ticket.queue_no)


def _late_position(ticket, setting):
    """Position for a SKIPPED or MISSED patient who checks in (R7).

    They go after the next `grace_count` (3) checked-in patients. If other late
    patients were already slotted in at that spot, they go after those too.
    A fractional position (e.g. 10.5) slots them in without renumbering anyone.

    DESC.md example: line [6, 8, 10, 12, 13]
      late 2 checks in -> [6, 8, 10, 2, 12, 13]
      late 1 checks in -> [6, 8, 10, 2, 1, 12, 13]
    """
    line = list(waiting_line(ticket.queue_date, ticket.session).exclude(pk=ticket.pk))
    if not line:
        return Decimal(ticket.queue_no)            # nobody waiting: they're next anyway
    if setting.grace_count <= 0:
        return line[0].position - 1                # grace rule switched off: front of the line

    i = min(setting.grace_count, len(line)) - 1   # the 3rd patient (or the last, if fewer)
    while i + 1 < len(line) and _was_moved(line[i + 1]):
        i += 1                                     # step past earlier late arrivals
    after = line[i]

    if i + 1 == len(line):
        return after.position + 1                  # end of the line
    before = line[i + 1]
    position = ((after.position + before.position) / 2).quantize(CENT, rounding=ROUND_DOWN)
    if position == Decimal(ticket.queue_no) and position - CENT >= after.position:
        position -= CENT                           # keep it marked as "moved"
    return position


# ---------------------------------------------------------------------------
# Update: check in, call next, call again, start, complete, no show
# ---------------------------------------------------------------------------
@transaction.atomic
def check_in(*, checked_in_by, ticket_id, now=None) -> QueueTicket:
    """Mark the patient as arrived. The patient scans the clinic QR, or a nurse does it.

    WAITING            -> CHECKED_IN, keeps its position
    SKIPPED            -> CHECKED_IN, goes after the next 3 checked-in patients (R7)
    MISSED (1st time)  -> CHECKED_IN the same way, and is marked as rejoined (R8)
    """
    now = _local_now(now)
    setting = _lock_queue()
    ticket = _get_ticket_for_update(ticket_id)

    if not (_is_ticket_owner(checked_in_by, ticket) or
            (checked_in_by.is_authenticated and checked_in_by.role in DESK_STAFF)):
        raise PermissionDenied("You cannot check in this ticket.")

    if ticket.status == Status.CANCELLED:
        raise ValidationError("This ticket was cancelled. Please get a new number.")
    if ticket.status == Status.COMPLETED:
        raise ValidationError("This visit is already completed.")
    if (ticket.status == Status.EXPIRED or ticket.queue_date != now.date()
            or now >= session_end(ticket.queue_date, ticket.session, setting)):
        raise ValidationError("This ticket has expired. Please get a new number.")
    if ticket.status in (Status.CHECKED_IN, Status.CALLED, Status.IN_CONSULTATION):
        raise ValidationError("You are already checked in.")
    if ticket.status == Status.MISSED and ticket.rejoined:
        raise ValidationError("This ticket has already rejoined once and can't rejoin again.")

    fields = ["status", "checked_in_at"]
    if ticket.status in (Status.SKIPPED, Status.MISSED):
        ticket.position = _late_position(ticket, setting)
        fields.append("position")
    if ticket.status == Status.MISSED:
        ticket.rejoined = True
        fields.append("rejoined")

    ticket.status = Status.CHECKED_IN
    ticket.checked_in_at = now
    ticket.save(update_fields=fields)
    return ticket


@transaction.atomic
def call_next(*, called_by, now=None) -> QueueTicket:
    """Call the next checked-in patient into the consultation room (R5, R6, R11, R12).

    Anyone still WAITING (not arrived) with a smaller position is SKIPPED (R7).
    """
    _require_role(called_by, QUEUE_STAFF, "Only clinic staff can call patients.")
    now = _local_now(now)
    setting = _lock_queue()
    _mark_overdue_calls_missed(now, setting)

    session = current_session(now, setting)
    if session is None:
        raise ValidationError(closed_message(setting))
    today = now.date()

    busy = QueueTicket.objects.filter(queue_date=today, session=session, status__in=SERVING_STATUSES).first()
    if busy:
        where = "has been called" if busy.status == Status.CALLED else "is with the doctor"
        raise ValidationError(
            f"Patient {busy.queue_no:03d} {where}. Complete the visit or mark a no-show first."
        )

    ticket = waiting_line(today, session).select_for_update().first()
    if ticket is None:
        raise ValidationError("No checked-in patients are waiting.")

    # R7: not arrived yet and a bigger number is being called -> skipped
    QueueTicket.objects.filter(
        queue_date=today, session=session, status=Status.WAITING, position__lt=ticket.position,
    ).update(status=Status.SKIPPED)

    ticket.status = Status.CALLED
    ticket.called_at = now
    ticket.called_alert_sent = False  # TODO (alerts): send the "It's your turn" WhatsApp
    fields = ["status", "called_at", "called_alert_sent"]
    if ticket.doctor_id is None:
        ticket.doctor = doctor_on_duty(today, session)
        fields.append("doctor")
    ticket.save(update_fields=fields)
    return ticket


@transaction.atomic
def call_again(*, called_by, ticket_id, now=None) -> QueueTicket:
    """Call the same patient again (restarts the 3-minute no-show timer)."""
    _require_role(called_by, QUEUE_STAFF, "Only clinic staff can call patients.")
    _lock_queue()
    ticket = _get_ticket_for_update(ticket_id)
    if ticket.status != Status.CALLED:
        raise ValidationError("Only a called patient can be called again.")
    ticket.called_at = _local_now(now)
    ticket.called_alert_sent = False  # TODO (alerts): send the WhatsApp again
    ticket.save(update_fields=["called_at", "called_alert_sent"])
    return ticket


@transaction.atomic
def start_consultation(*, started_by, ticket_id, now=None) -> QueueTicket:
    """The called patient has entered the room: CALLED -> IN_CONSULTATION."""
    _require_role(started_by, QUEUE_STAFF, "Only clinic staff can start a consultation.")
    _lock_queue()
    ticket = _get_ticket_for_update(ticket_id)
    if ticket.status != Status.CALLED:
        raise ValidationError("Only a called patient can start a consultation.")

    ticket.status = Status.IN_CONSULTATION
    ticket.started_at = _local_now(now)
    fields = ["status", "started_at"]
    if started_by.role == "DOCTOR" and hasattr(started_by, "staff"):
        ticket.doctor = started_by.staff  # the doctor who actually saw the patient
        fields.append("doctor")
    ticket.save(update_fields=fields)
    return ticket


@transaction.atomic
def complete_ticket(*, completed_by, ticket_id, now=None) -> QueueTicket:
    """The consultation is over: IN_CONSULTATION -> COMPLETED.

    The doctor then writes the Consultation record from this ticket.
    """
    _require_role(completed_by, QUEUE_STAFF, "Only clinic staff can complete a visit.")
    _lock_queue()
    ticket = _get_ticket_for_update(ticket_id)
    if ticket.status != Status.IN_CONSULTATION:
        raise ValidationError("Only a patient who is with the doctor can be completed.")
    ticket.status = Status.COMPLETED
    ticket.completed_at = _local_now(now)
    ticket.save(update_fields=["status", "completed_at"])
    return ticket


def _mark_missed(ticket, now):
    """A called patient didn't come (R8). 1st miss -> MISSED (may rejoin once); 2nd -> CANCELLED."""
    ticket.miss_count += 1
    if ticket.miss_count >= 2:
        ticket.status = Status.CANCELLED
        ticket.cancelled_at = now
    else:
        ticket.status = Status.MISSED
    ticket.save(update_fields=["miss_count", "status", "cancelled_at"])
    return ticket


@transaction.atomic
def mark_no_show(*, marked_by, ticket_id, now=None) -> QueueTicket:
    """The "No show" button: the called patient didn't come in."""
    _require_role(marked_by, QUEUE_STAFF, "Only clinic staff can mark a no-show.")
    _lock_queue()
    ticket = _get_ticket_for_update(ticket_id)
    if ticket.status != Status.CALLED:
        raise ValidationError("Only a called patient can be marked as a no-show.")
    return _mark_missed(ticket, _local_now(now))


# ---------------------------------------------------------------------------
# Delete: cancel (soft delete, the row is kept)
# ---------------------------------------------------------------------------
@transaction.atomic
def cancel_ticket(*, cancelled_by, ticket_id, now=None) -> QueueTicket:
    """Cancel a ticket. Patients can cancel their own; nurses and admins any."""
    _lock_queue()
    ticket = _get_ticket_for_update(ticket_id)
    if not (_is_ticket_owner(cancelled_by, ticket) or
            (cancelled_by.is_authenticated and cancelled_by.role in DESK_STAFF)):
        raise PermissionDenied("You cannot cancel this ticket.")
    if ticket.status == Status.IN_CONSULTATION:
        raise ValidationError("The patient is with the doctor, so this ticket can't be cancelled.")
    if ticket.status not in OPEN_STATUSES:
        raise ValidationError(f"This ticket is already {ticket.get_status_display().lower()}.")

    ticket.status = Status.CANCELLED
    ticket.cancelled_at = _local_now(now)
    ticket.save(update_fields=["status", "cancelled_at"])
    return ticket


# ---------------------------------------------------------------------------
# Housekeeping: run on every queue page load / 5-second refresh
# ---------------------------------------------------------------------------
def _overdue_calls(now, setting):
    limit = now - dt.timedelta(minutes=setting.miss_timeout_min)
    return QueueTicket.objects.filter(status=Status.CALLED, called_at__lte=limit)


def _mark_overdue_calls_missed(now, setting):
    """Called more than miss_timeout_min (3) minutes ago and still not started -> missed (R8)."""
    tickets = list(_overdue_calls(now, setting).select_for_update())
    for ticket in tickets:
        _mark_missed(ticket, now)
    return len(tickets)


def _expirable(now, setting):
    """Unfinished tickets whose session has ended (R9). IN_CONSULTATION is left to finish."""
    today = now.date()
    ended = Q(queue_date__lt=today)
    for session in (Session.MORNING, Session.NIGHT):
        if now >= session_end(today, session, setting):
            ended |= Q(queue_date=today, session=session)
    to_expire = [s for s in OPEN_STATUSES if s != Status.IN_CONSULTATION]
    return QueueTicket.objects.filter(ended, status__in=to_expire)


def run_housekeeping(now=None):
    """Apply the time-based rules: no-show after 3 min (R8) and expiry at session end (R9).

    Cheap when there's nothing to do (two quick reads, no lock), so views can
    call it on every page load. Returns {"missed": n, "expired": n}.
    """
    now = _local_now(now)
    setting = ClinicSetting.load()
    if not (_overdue_calls(now, setting).exists() or _expirable(now, setting).exists()):
        return {"missed": 0, "expired": 0}

    with transaction.atomic():
        setting = _lock_queue()
        missed = _mark_overdue_calls_missed(now, setting)
        expired = _expirable(now, setting).update(status=Status.EXPIRED)
    return {"missed": missed, "expired": expired}


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------
def get_todays_ticket(patient, now=None):
    """The patient's open ticket for today, or None.

    Open = WAITING, CHECKED_IN, SKIPPED, CALLED, IN_CONSULTATION or MISSED
    (a missed ticket can still rejoin once). R3 allows only one.
    """
    if patient is None:
        return None
    return (
        QueueTicket.objects.filter(
            patient=patient, queue_date=_local_now(now).date(), status__in=OPEN_STATUSES,
        )
        .select_related("doctor")
        .order_by("-issued_at")
        .first()
    )


def now_serving(date, session):
    """The ticket that is called or with the doctor right now, or None (R12: at most one)."""
    return QueueTicket.objects.filter(
        queue_date=date, session=session, status__in=SERVING_STATUSES,
    ).first()


def people_ahead(ticket):
    """How many patients will be called before this ticket, or None if it isn't in line.

    CHECKED_IN: checked-in patients before it in calling order (R6, R11).
    WAITING:    checked-in patients with a smaller position (where they'd be if they
                arrived now).
    CALLED / IN_CONSULTATION: 0. SKIPPED / MISSED: None (they must check in again).
    """
    line = waiting_line(ticket.queue_date, ticket.session)
    if ticket.status == Status.CHECKED_IN:
        before = Q(position__lt=ticket.position)
        if ticket.checked_in_at is None:
            # No check-in time (e.g. edited in the admin): treat it as the last to check in.
            before |= Q(position=ticket.position, checked_in_at__isnull=False)
        else:
            before |= Q(position=ticket.position, checked_in_at__lt=ticket.checked_in_at)
            before |= Q(position=ticket.position, checked_in_at=ticket.checked_in_at, ticket_id__lt=ticket.pk)
        return line.exclude(pk=ticket.pk).filter(before).count()
    if ticket.status == Status.WAITING:
        return line.filter(position__lt=ticket.position).count()
    if ticket.status in SERVING_STATUSES:
        return 0
    return None


def average_consult_minutes(date, setting=None):
    """Today's average consultation time in minutes (default_consult_min until someone is seen)."""
    setting = setting or ClinicSetting.load()
    done = QueueTicket.objects.filter(
        queue_date=date, status=Status.COMPLETED,
        started_at__isnull=False, completed_at__isnull=False,
    ).values_list("started_at", "completed_at")
    minutes = [(end - start).total_seconds() / 60 for start, end in done if end > start]
    if not minutes:
        return setting.default_consult_min
    return max(1, round(sum(minutes) / len(minutes)))


def live_status(ticket, now=None):
    """Everything the My queue page shows for a ticket.

    Returns a dict:
        ticket, now_serving      - tickets (now_serving may be None)
        ahead                    - people ahead, or None if not in line
        place                    - "You are Nth in line" (checked-in only), else None
        wait_min, wait_max       - estimated wait range in minutes, or None
        avg_consult_min          - today's average consultation time
        come_now                 - True at near_alert_threshold (3) or fewer ahead
        pushed_back              - True if more people are ahead than last time (late
                                   patients rejoined ahead): show the ▲ note
    Also remembers the ahead count in ticket.last_ahead for the next refresh.
    """
    setting = ClinicSetting.load()
    ahead = people_ahead(ticket)
    avg = average_consult_minutes(ticket.queue_date, setting)

    pushed_back = ahead is not None and ticket.last_ahead is not None and ahead > ticket.last_ahead
    if ahead is not None and ahead != ticket.last_ahead:
        QueueTicket.objects.filter(pk=ticket.pk).update(last_ahead=ahead)
        ticket.last_ahead = ahead

    in_line = ticket.status in (Status.WAITING, Status.CHECKED_IN)
    come_now = in_line and ahead is not None and ahead <= setting.near_alert_threshold
    # TODO (alerts): when come_now and not ticket.near_alert_sent, send the
    # "Please come now" WhatsApp and set near_alert_sent = True.

    return {
        "ticket": ticket,
        "now_serving": now_serving(ticket.queue_date, ticket.session),
        "ahead": ahead,
        "place": ahead + 1 if ticket.status == Status.CHECKED_IN else None,
        "wait_min": ahead * avg if in_line and ahead is not None else None,
        "wait_max": (ahead + 1) * avg if in_line and ahead is not None else None,
        "avg_consult_min": avg,
        "come_now": come_now,
        "pushed_back": pushed_back,
    }
