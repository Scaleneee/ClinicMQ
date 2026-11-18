"""
accounts/staff_views.py
Staff & Schedule screens (UI.md §5.5). Views stay thin: they call accounts/services.py.

Everyone on the staff can view the staff list and roster; only admins change them.
"""

import datetime as dt

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import services as acc
from .decorators import role_required
from .models import Session, Shift, Staff, User
from .staff_forms import ShiftForm, StaffForm

STAFF_ROLES = ("NURSE", "DOCTOR", "ADMIN")

ROLE_FILTERS = [
    ("all", "All", None),
    ("doctors", "Doctors", User.Role.DOCTOR),
    ("nurses", "Nurses", User.Role.NURSE),
    ("admins", "Admins", User.Role.ADMIN),
]


def _add_service_errors(form, error, field_map=None):
    """Show a ValidationError from a service under the matching form fields.

    field_map renames service keys to form fields, e.g. {"password": "password1"}.
    """
    field_map = field_map or {}
    if hasattr(error, "error_dict"):
        for field, field_messages in error.message_dict.items():
            field = field_map.get(field, field)
            target = field if field in form.fields else None
            for message in field_messages:
                form.add_error(target, message)
    else:
        for message in error.messages:
            form.add_error(None, message)


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


# ---------------------------------------------------------------------------
# Retrieve: staff list
# ---------------------------------------------------------------------------
@role_required(*STAFF_ROLES)
def staff_list(request):
    key = request.GET.get("role", "all")
    if key not in {k for k, _, _ in ROLE_FILTERS}:
        key = "all"
    query = request.GET.get("q", "").strip()

    everyone = list(acc.list_staff(viewed_by=request.user, query=query))
    pills, shown = [], everyone
    for k, label, role in ROLE_FILTERS:
        matching = everyone if role is None else [s for s in everyone if s.user.role == role]
        pills.append({"key": k, "label": label, "count": len(matching), "active": k == key})
        if k == key:
            shown = matching

    return render(request, "accounts/staff/staff_list.html", {
        "staff": shown,
        "pills": pills,
        "role_key": key,
        "query": query,
        "is_admin": request.user.role == "ADMIN",
    })


# ---------------------------------------------------------------------------
# Create / update staff (admin)
# ---------------------------------------------------------------------------
@role_required("ADMIN")
def staff_create(request):
    form = StaffForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            staff = acc.create_staff(
                created_by=request.user, full_name=data["full_name"], email=data["email"], role=data["role"],
                phone=data["phone"], specialty=data["specialty"], password=data["password1"],
            )
        except ValidationError as e:
            _add_service_errors(form, e, {"password": "password1"})
        except PermissionDenied as e:
            messages.error(request, str(e))
        else:
            messages.success(request, f"{acc.display_name(staff)} was added. They can log in with {staff.user.email}.")
            return redirect("staff_list")
    return render(request, "accounts/staff/staff_form.html", {"form": form, "staff": None})


@role_required("ADMIN")
def staff_edit(request, pk):
    staff = get_object_or_404(Staff.objects.select_related("user"), pk=pk)
    initial = {"full_name": staff.full_name, "email": staff.user.email, "role": staff.user.role,
               "phone": staff.phone, "specialty": staff.specialty}
    form = StaffForm(request.POST or None, initial=initial, editing=True)
    if request.method == "POST" and form.is_valid():
        try:
            staff = acc.update_staff(updated_by=request.user, staff_id=staff.pk, **form.cleaned_data)
        except ValidationError as e:
            _add_service_errors(form, e)
        except PermissionDenied as e:
            messages.error(request, str(e))
        else:
            messages.success(request, f"{acc.display_name(staff)}'s details were saved.")
            return redirect("staff_list")
    return render(request, "accounts/staff/staff_form.html", {
        "form": form,
        "staff": staff,
        "upcoming": acc.upcoming_shifts(staff),
    })


# ---------------------------------------------------------------------------
# Delete: deactivate / reactivate (admin)
# ---------------------------------------------------------------------------
@require_POST
@role_required("ADMIN")
def staff_deactivate(request, pk):
    _run(request, lambda: acc.deactivate_staff(deactivated_by=request.user, staff_id=pk),
         lambda s: f"{acc.display_name(s)} was deactivated and can no longer log in.")
    return redirect("staff_list")


@require_POST
@role_required("ADMIN")
def staff_reactivate(request, pk):
    _run(request, lambda: acc.reactivate_staff(reactivated_by=request.user, staff_id=pk),
         lambda s: f"{acc.display_name(s)} was reactivated and can log in again.")
    return redirect("staff_list")


# ---------------------------------------------------------------------------
# Schedule: weekly roster (all staff can view)
# ---------------------------------------------------------------------------
def _week_label(start):
    end = start + dt.timedelta(days=6)
    if start.month == end.month:
        return f"{start.day}–{end.day} {end:%b %Y}"
    if start.year == end.year:
        return f"{start.day} {start:%b} – {end.day} {end:%b %Y}"
    return f"{start.day} {start:%b %Y} – {end.day} {end:%b %Y}"


def _parse_week(value):
    try:
        return acc.week_start(dt.date.fromisoformat(value))
    except (TypeError, ValueError):
        return acc.week_start()


@role_required(*STAFF_ROLES)
def roster(request):
    from queueing.services import session_hours

    start = _parse_week(request.GET.get("week"))
    days = acc.week_roster(start, viewed_by=request.user)
    sessions = []
    for session in (Session.MORNING, Session.NIGHT):
        begin, end = session_hours(session)
        sessions.append({
            "key": session,
            "label": Session(session).label,
            "hours": f"{begin:%I:%M %p}".lstrip("0") + " – " + f"{end:%I:%M %p}".lstrip("0"),
            "cells": [{"day": d, "shifts": d["sessions"][session],
                       "has_doctor": any(s.staff.user.role == User.Role.DOCTOR and s.staff.user.is_active
                                         for s in d["sessions"][session])} for d in days],
        })
    return render(request, "accounts/staff/roster.html", {
        "days": days,
        "sessions": sessions,
        "week_label": _week_label(start),
        "prev_week": (start - dt.timedelta(days=7)).isoformat(),
        "next_week": (start + dt.timedelta(days=7)).isoformat(),
        "this_week": acc.week_start(),
        "start": start,
        "is_admin": request.user.role == "ADMIN",
    })


# ---------------------------------------------------------------------------
# Schedule: add / edit / remove shifts (admin)
# ---------------------------------------------------------------------------
def _staff_choices():
    """Active staff, doctors first: [(id, "Dr. Aisyah Rahman · Doctor"), ...]"""
    order = {User.Role.DOCTOR: 0, User.Role.NURSE: 1, User.Role.ADMIN: 2}
    staff = Staff.objects.filter(user__is_active=True).select_related("user")
    return [(s.pk, f"{acc.display_name(s)} · {s.user.get_role_display()}")
            for s in sorted(staff, key=lambda s: (order[s.user.role], s.full_name))]


def _roster_url_for(day):
    from django.urls import reverse
    return f"{reverse('roster')}?week={acc.week_start(day).isoformat()}"


@role_required("ADMIN")
def shift_create(request):
    initial = {}
    if request.GET.get("date"):
        initial["shift_date"] = request.GET["date"]
    if request.GET.get("session") in (Session.MORNING, Session.NIGHT):
        initial["session"] = request.GET["session"]
    form = ShiftForm(request.POST or None, initial=initial, staff_choices=_staff_choices())

    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            shift = acc.add_shift(added_by=request.user, staff_id=data["staff"],
                                  shift_date=data["shift_date"], session=data["session"])
        except ValidationError as e:
            _add_service_errors(form, e)
        except PermissionDenied as e:
            messages.error(request, str(e))
        else:
            messages.success(request, f"{acc.display_name(shift.staff)} added to {shift.shift_date:%a %d %b} "
                                      f"({shift.get_session_display().lower()}).")
            return redirect(_roster_url_for(shift.shift_date))

    back = _roster_url_for(dt.date.fromisoformat(request.GET["week"])) if request.GET.get("week") else None
    return render(request, "accounts/staff/shift_form.html", {"form": form, "shift": None, "back_url": back})


@role_required("ADMIN")
def shift_edit(request, pk):
    shift = get_object_or_404(Shift.objects.select_related("staff"), pk=pk)
    if shift.shift_date < timezone.localdate():
        messages.error(request, "Past shifts are kept as history and can't be changed.")
        return redirect(_roster_url_for(shift.shift_date))

    initial = {"staff": shift.staff_id, "shift_date": shift.shift_date, "session": shift.session}
    form = ShiftForm(request.POST or None, initial=initial, staff_choices=_staff_choices())
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            shift = acc.update_shift(updated_by=request.user, shift_id=shift.pk, staff_id=data["staff"],
                                     shift_date=data["shift_date"], session=data["session"])
        except ValidationError as e:
            _add_service_errors(form, e)
        except PermissionDenied as e:
            messages.error(request, str(e))
        else:
            messages.success(request, "Shift saved.")
            return redirect(_roster_url_for(shift.shift_date))

    return render(request, "accounts/staff/shift_form.html", {
        "form": form, "shift": shift, "back_url": _roster_url_for(shift.shift_date),
    })


@require_POST
@role_required("ADMIN")
def shift_delete(request, pk):
    shift = get_object_or_404(Shift.objects.select_related("staff"), pk=pk)
    day, name = shift.shift_date, acc.display_name(shift.staff)
    _run(request, lambda: acc.remove_shift(removed_by=request.user, shift_id=shift.pk),
         f"{name} removed from {day:%a %d %b}.")
    return redirect(_roster_url_for(day))
