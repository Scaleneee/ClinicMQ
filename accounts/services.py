"""
accounts/services.py
Business logic for the Staff & Schedule module. Views call these functions; keep views thin.

Rules (DESC.md, Module 3):
  - Only admins add, edit, deactivate and reactivate staff, and manage shifts
  - Email is unique; it is also the username (everyone logs in with email)
  - Role is DOCTOR, NURSE or ADMIN
  - Deactivated staff cannot log in; an admin can't deactivate themself or the last admin
  - Only one doctor per session; a staff member works a session only once
  - Shifts are for today onwards; past shifts are kept as read-only history

Errors: ValidationError (message for the user) and PermissionDenied (wrong role).
"""

import datetime as dt

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.validators import validate_email
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from patients.services import PHONE_PATTERN, normalize_phone

from .models import Session, Shift, Staff

User = get_user_model()

STAFF_ROLES = {"DOCTOR", "NURSE", "ADMIN"}


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def _require_admin(user, message="Only admins can manage staff and schedules."):
    if not user.is_authenticated or user.role != "ADMIN":
        raise PermissionDenied(message)


def _require_staff(user):
    if not user.is_authenticated or user.role not in STAFF_ROLES:
        raise PermissionDenied("Only clinic staff can view this.")


def _clean_name(raw):
    return " ".join((raw or "").split())


def display_name(staff):
    """'Dr. Aisyah Rahman' for doctors, otherwise the full name."""
    return f"Dr. {staff.full_name}" if staff.role == Staff.Role.DOCTOR else staff.full_name


# ---------------------------------------------------------------------------
# Who is on duty (used by the queue)
# ---------------------------------------------------------------------------
def staff_on_duty(date, session, role=None):
    """Active staff with a shift on `date` for `session` ("MORNING" / "NIGHT").

    Deactivated staff and staff whose login is disabled are left out.
    Optionally filter by role ("DOCTOR", "NURSE", "ADMIN").
    """
    staff = Staff.objects.filter(
        is_active=True,
        user__is_active=True,
        shifts__shift_date=date,
        shifts__session=session,
    )
    if role:
        staff = staff.filter(role=role)
    return staff.select_related("user").order_by("full_name").distinct()


def doctor_on_duty(date, session):
    """The doctor working this session, or None (no doctor means no queue numbers).

    The clinic has one doctor per session; if two were rostered by mistake,
    the first by name is returned.
    """
    return staff_on_duty(date, session, role=Staff.Role.DOCTOR).first()


# ---------------------------------------------------------------------------
# Retrieve: staff list
# ---------------------------------------------------------------------------
def list_staff(*, viewed_by, role=None, query=""):
    """Staff for the list page: optional role filter and search by name, email or role."""
    _require_staff(viewed_by)
    staff = Staff.objects.select_related("user")
    if role in STAFF_ROLES:
        staff = staff.filter(role=role)
    query = (query or "").strip()
    if query:
        staff = staff.filter(
            Q(full_name__icontains=query) | Q(user__email__icontains=query) | Q(role__iexact=query)
        )
    return staff.order_by("-is_active", "role", "full_name")


# ---------------------------------------------------------------------------
# Create / update staff (admin)
# ---------------------------------------------------------------------------
def _validate_staff_fields(*, full_name, email, role, phone, exclude_user_id=None):
    """Clean and check the shared staff fields. Returns the cleaned values."""
    full_name = _clean_name(full_name)
    email = (email or "").strip().lower()
    role = (role or "").strip().upper()
    phone = normalize_phone(phone)
    errors = {}

    if not full_name:
        errors["full_name"] = "Full name is required."
    elif len(full_name) > 100:
        errors["full_name"] = "Full name must be at most 100 characters."

    try:
        validate_email(email)
    except ValidationError:
        errors["email"] = "Enter a valid email address."
    else:
        taken = User.objects.filter(Q(email__iexact=email) | Q(username__iexact=email))
        if exclude_user_id:
            taken = taken.exclude(pk=exclude_user_id)
        if taken.exists():
            errors["email"] = "An account with this email already exists."

    if role not in STAFF_ROLES:
        errors["role"] = "Role must be Doctor, Nurse or Admin."
    if not PHONE_PATTERN.match(phone):
        errors["phone"] = "Phone must be in the format 01X-XXXXXXX."

    return errors, {"full_name": full_name, "email": email, "role": role, "phone": phone}


@transaction.atomic
def create_staff(*, created_by, full_name, email, role, phone, password, specialty=None) -> Staff:
    """Add a doctor, nurse or admin: a login account (email = username) plus its Staff record."""
    _require_admin(created_by)
    errors, data = _validate_staff_fields(full_name=full_name, email=email, role=role, phone=phone)
    try:
        validate_password(password, user=User(email=data["email"], username=data["email"]))
    except ValidationError as e:
        errors["password"] = e.messages
    if errors:
        raise ValidationError(errors)

    specialty = (specialty or "").strip() or None
    try:
        user = User.objects.create_user(
            username=data["email"], email=data["email"], password=password, role=data["role"],
        )
    except IntegrityError:
        raise ValidationError({"email": "An account with this email already exists."})
    return Staff.objects.create(
        user=user,
        full_name=data["full_name"],
        role=data["role"],
        phone=data["phone"],
        specialty=specialty if data["role"] == Staff.Role.DOCTOR else None,
    )


@transaction.atomic
def update_staff(*, updated_by, staff_id, full_name, email, role, phone, specialty=None) -> Staff:
    """Edit details or role. The login account (email, username, role) changes with it."""
    _require_admin(updated_by)
    staff = _get_staff_for_update(staff_id)
    errors, data = _validate_staff_fields(full_name=full_name, email=email, role=role, phone=phone,
                                          exclude_user_id=staff.user_id)

    if not errors.get("role") and data["role"] != staff.role:
        if staff.role == Staff.Role.ADMIN and staff.is_active and _active_admin_count() <= 1:
            errors["role"] = "This is the only active admin, so the role can't be changed."
        elif staff.user_id == updated_by.id:
            errors["role"] = "You can't change your own role."
        elif data["role"] == Staff.Role.DOCTOR:
            clash = _doctor_clashes(staff)
            if clash:
                errors["role"] = clash
    if errors:
        raise ValidationError(errors)

    staff.full_name = data["full_name"]
    staff.role = data["role"]
    staff.phone = data["phone"]
    staff.specialty = ((specialty or "").strip() or None) if data["role"] == Staff.Role.DOCTOR else None
    staff.save()

    user = staff.user
    user.email = data["email"]
    user.username = data["email"]
    user.role = data["role"]
    try:
        user.save(update_fields=["email", "username", "role"])
    except IntegrityError:
        raise ValidationError({"email": "An account with this email already exists."})
    return staff


# ---------------------------------------------------------------------------
# Delete: deactivate / reactivate (admin)
# ---------------------------------------------------------------------------
def _get_staff_for_update(staff_id):
    try:
        return Staff.objects.select_for_update().select_related("user").get(pk=staff_id)
    except Staff.DoesNotExist:
        raise ValidationError("Staff member not found.")


def _active_admin_count():
    return Staff.objects.filter(role=Staff.Role.ADMIN, is_active=True, user__is_active=True).count()


@transaction.atomic
def deactivate_staff(*, deactivated_by, staff_id) -> Staff:
    """Deactivate instead of deleting (their records stay). They can no longer log in."""
    _require_admin(deactivated_by)
    staff = _get_staff_for_update(staff_id)
    if not staff.is_active:
        raise ValidationError(f"{staff.full_name} is already deactivated.")
    if staff.user_id == deactivated_by.id:
        raise ValidationError("You can't deactivate your own account.")
    if staff.role == Staff.Role.ADMIN and _active_admin_count() <= 1:
        raise ValidationError("This is the only active admin, so it can't be deactivated.")

    staff.is_active = False
    staff.save(update_fields=["is_active"])
    staff.user.is_active = False
    staff.user.save(update_fields=["is_active"])
    return staff


@transaction.atomic
def reactivate_staff(*, reactivated_by, staff_id) -> Staff:
    """Let a deactivated staff member log in and work again."""
    _require_admin(reactivated_by)
    staff = _get_staff_for_update(staff_id)
    if staff.is_active and staff.user.is_active:
        raise ValidationError(f"{staff.full_name} is already active.")
    if staff.role == Staff.Role.DOCTOR:
        clash = _doctor_clashes(staff)
        if clash:
            raise ValidationError(clash)

    staff.is_active = True
    staff.save(update_fields=["is_active"])
    staff.user.is_active = True
    staff.user.save(update_fields=["is_active"])
    return staff


def _doctor_clashes(staff):
    """If `staff` became/returned as a doctor, would any upcoming shift have two doctors?"""
    today = timezone.localdate()
    for shift in staff.shifts.filter(shift_date__gte=today).order_by("shift_date", "session"):
        other = doctor_on_duty(shift.shift_date, shift.session)
        if other and other.pk != staff.pk:
            return (f"{display_name(other)} is already on duty on {shift.shift_date:%d/%m/%Y} "
                    f"({shift.get_session_display().lower()}). Remove one of the shifts first.")
    return None


# ---------------------------------------------------------------------------
# Schedule: weekly roster
# ---------------------------------------------------------------------------
def week_start(day=None):
    """Monday of the week containing `day` (default today)."""
    day = day or timezone.localdate()
    return day - dt.timedelta(days=day.weekday())


def week_roster(start, *, viewed_by):
    """7 days × Morning/Night for the week starting on Monday `start`.

    Returns a list of days: {"date", "is_today", "is_past", "sessions": {"MORNING": [shift…], "NIGHT": [...]}}
    Each shift has .staff loaded; doctors are listed first.
    """
    _require_staff(viewed_by)
    days = [start + dt.timedelta(days=i) for i in range(7)]
    shifts = (
        Shift.objects.filter(shift_date__range=(days[0], days[-1]))
        .select_related("staff", "staff__user")
        .order_by("shift_date", "session", "staff__role", "staff__full_name")
    )
    today = timezone.localdate()
    roster = [{"date": d, "is_today": d == today, "is_past": d < today,
               "sessions": {Session.MORNING: [], Session.NIGHT: []}} for d in days]
    by_date = {r["date"]: r for r in roster}
    for shift in shifts:
        by_date[shift.shift_date]["sessions"][shift.session].append(shift)
    for r in roster:  # doctors first, then nurses, then admins
        for session in r["sessions"]:
            r["sessions"][session].sort(key=lambda s: (["DOCTOR", "NURSE", "ADMIN"].index(s.staff.role),
                                                       s.staff.full_name))
    return roster


def upcoming_shifts(staff, limit=5):
    return staff.shifts.filter(shift_date__gte=timezone.localdate()).order_by("shift_date", "session")[:limit]


# ---------------------------------------------------------------------------
# Schedule: add / edit / remove shifts (admin)
# ---------------------------------------------------------------------------
def _check_shift(*, staff, shift_date, session, exclude_shift_id=None):
    """Field errors for a shift, or {}."""
    errors = {}
    today = timezone.localdate()
    if session not in (Session.MORNING, Session.NIGHT):
        errors["session"] = "Session must be Morning or Night."
    if shift_date is None:
        errors["shift_date"] = "Date is required."
    elif shift_date < today:
        errors["shift_date"] = "Shifts can only be added for today or later."
    if staff is not None and not (staff.is_active and staff.user.is_active):
        errors["staff"] = f"{staff.full_name} is deactivated. Reactivate them first."
    if errors or staff is None:
        return errors

    same = Shift.objects.filter(staff=staff, shift_date=shift_date, session=session)
    if exclude_shift_id:
        same = same.exclude(pk=exclude_shift_id)
    if same.exists():
        errors["staff"] = f"{display_name(staff)} already works this session."
    elif staff.role == Staff.Role.DOCTOR:
        others = (Shift.objects.filter(shift_date=shift_date, session=session, staff__role=Staff.Role.DOCTOR,
                                       staff__is_active=True, staff__user__is_active=True)
                  .exclude(staff=staff).select_related("staff"))
        if exclude_shift_id:
            others = others.exclude(pk=exclude_shift_id)
        other = others.first()
        if other:  # one room, one doctor
            errors["staff"] = f"{display_name(other.staff)} is already on duty for this session."
    return errors


def _get_staff(staff_id):
    try:
        return Staff.objects.select_related("user").get(pk=staff_id)
    except (Staff.DoesNotExist, ValueError, TypeError):
        return None


@transaction.atomic
def add_shift(*, added_by, staff_id, shift_date, session) -> Shift:
    _require_admin(added_by)
    staff = _get_staff(staff_id)
    errors = {} if staff else {"staff": "Choose a staff member."}
    errors.update(_check_shift(staff=staff, shift_date=shift_date, session=session))
    if errors:
        raise ValidationError(errors)
    try:
        return Shift.objects.create(staff=staff, shift_date=shift_date, session=session)
    except IntegrityError:
        raise ValidationError({"staff": f"{display_name(staff)} already works this session."})


@transaction.atomic
def update_shift(*, updated_by, shift_id, staff_id, shift_date, session) -> Shift:
    _require_admin(updated_by)
    shift = _get_shift_for_update(shift_id)
    staff = _get_staff(staff_id)
    errors = {} if staff else {"staff": "Choose a staff member."}
    errors.update(_check_shift(staff=staff, shift_date=shift_date, session=session, exclude_shift_id=shift.pk))
    if errors:
        raise ValidationError(errors)
    shift.staff, shift.shift_date, shift.session = staff, shift_date, session
    try:
        shift.save()
    except IntegrityError:
        raise ValidationError({"staff": f"{display_name(staff)} already works this session."})
    return shift


@transaction.atomic
def remove_shift(*, removed_by, shift_id) -> None:
    _require_admin(removed_by)
    shift = _get_shift_for_update(shift_id)
    shift.delete()


def _get_shift_for_update(shift_id):
    try:
        shift = Shift.objects.select_for_update().get(pk=shift_id)
    except Shift.DoesNotExist:
        raise ValidationError("Shift not found.")
    if shift.shift_date < timezone.localdate():
        raise ValidationError("Past shifts are kept as history and can't be changed.")
    return shift
