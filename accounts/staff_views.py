"""
accounts/staff_views.py
Staff & Schedule screens (UI.md §5.5). Views stay thin: they call accounts/services.py.

Everyone on the staff can view the staff list and roster; only admins change them.
"""

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import render

from . import services as acc
from .decorators import role_required
from .models import Staff

STAFF_ROLES = ("NURSE", "DOCTOR", "ADMIN")

ROLE_FILTERS = [
    ("all", "All", None),
    ("doctors", "Doctors", Staff.Role.DOCTOR),
    ("nurses", "Nurses", Staff.Role.NURSE),
    ("admins", "Admins", Staff.Role.ADMIN),
]


def _add_service_errors(form, error):
    """Show a ValidationError from a service under the matching form fields."""
    if hasattr(error, "error_dict"):
        for field, field_messages in error.message_dict.items():
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
        matching = everyone if role is None else [s for s in everyone if s.role == role]
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
