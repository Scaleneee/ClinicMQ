"""Accounts services: e.g. create_staff(), assign_shift(), staff_on_duty(date, session).

Business logic for this app. Views call these functions; keep views thin.
Wrap multi-step writes in transaction.atomic().
"""

from .models import Staff


# ---------------------------------------------------------------------------
# Who is on duty (Staff & Schedule module, used by the queue)
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
