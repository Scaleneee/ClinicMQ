"""
accounts/dashboards.py
Staff home pages after login (UI.md §5.2): nurse and admin dashboards.

They only read data from the other modules (queue, medicine, billing); every
change still happens on that module's own pages.
"""

import datetime as dt
from decimal import Decimal

from django.db.models import DecimalField, ExpressionWrapper, F, Q, Sum
from django.shortcuts import render
from django.utils import timezone

from billing.models import Bill, BillItem
from pharmacy.models import Medicine, PrescriptionItem
from queueing import services as q
from queueing.models import QueueTicket

from . import services as acc

EXPIRING_DAYS = 30  # "expiring soon" = expires within this many days


# ---------------------------------------------------------------------------
# Shared numbers
# ---------------------------------------------------------------------------
def stock_alerts(limit=None):
    """Active medicines that need attention: out of stock, low stock or expiring soon.

    Each medicine gets .alert ("Out of stock" / "Low stock" / "Expiring soon") and
    .alert_style (badge style), most urgent first.
    """
    today = timezone.localdate()
    soon = today + dt.timedelta(days=EXPIRING_DAYS)
    meds = Medicine.objects.filter(is_active=True).filter(
        Q(quantity__lte=F("reorder_level")) | Q(expiry_date__lte=soon)
    )
    alerts = []
    for m in meds:
        if m.quantity == 0:
            m.alert, m.alert_style, rank = "Out of stock", "out", 0
        elif m.expiry_date <= soon:
            m.alert, m.alert_style, rank = "Expiring soon", "missed", 1
        else:
            m.alert, m.alert_style, rank = "Low stock", "waiting", 2
        alerts.append((rank, m.quantity, m.name, m))
    alerts.sort(key=lambda a: a[:3])
    result = [a[3] for a in alerts]
    return result[:limit] if limit else result


def low_stock_count():
    return Medicine.objects.filter(is_active=True, quantity__lte=F("reorder_level")).count()


def to_dispense_count():
    """Consultations with prescription items that haven't been dispensed yet."""
    return (PrescriptionItem.objects.filter(dispensed=False)
            .values("consultation_id").distinct().count())


def _with_totals(bills):
    """Attach .total_amount (sum of the bill's items) without one query per bill."""
    bills = list(bills.select_related("consultation__ticket__patient").prefetch_related("items"))
    for b in bills:
        b.total_amount = sum((i.quantity * i.unit_price for i in b.items.all()), Decimal("0"))
    return bills


def unpaid_bills(limit=5):
    return _with_totals(Bill.objects.filter(status=Bill.Status.UNPAID).order_by("created_at")[:limit])


def revenue_on(day):
    """Money from bills paid on `day` (void bills don't count)."""
    line = ExpressionWrapper(F("quantity") * F("unit_price"), output_field=DecimalField(max_digits=12, decimal_places=2))
    total = (BillItem.objects.filter(bill__status=Bill.Status.PAID, bill__paid_at__date=day)
             .aggregate(total=Sum(line))["total"])
    return total or Decimal("0")


def _staff_name(user):
    try:
        return user.staff.full_name
    except Exception:  # account without a Staff record (e.g. the superuser)
        return user.get_full_name()


# ---------------------------------------------------------------------------
# Nurse dashboard
# ---------------------------------------------------------------------------
def nurse_dashboard(request):
    q.run_housekeeping()
    o = q.queue_overview()
    today = o["date"]
    todays = QueueTicket.objects.filter(queue_date=today)
    line = list(q.waiting_line(today, o["session"]).select_related("patient")[:8])
    for place, t in enumerate(line, start=1):
        t.place = place

    return render(request, "accounts/dashboard_nurse.html", {
        "name": _staff_name(request.user),
        "o": o,
        "stats": {
            "today": todays.exclude(status__in=[QueueTicket.Status.CANCELLED, QueueTicket.Status.EXPIRED]).count(),
            "checked_in": o["waiting"],
            "to_dispense": to_dispense_count(),
            "low_stock": low_stock_count(),
        },
        "line": line,
        "serving": o["now_serving"],
        "alerts": stock_alerts(limit=5),
        "unpaid": unpaid_bills(limit=5),
    })


# ---------------------------------------------------------------------------
# Admin dashboard
# ---------------------------------------------------------------------------
def admin_dashboard(request):
    q.run_housekeeping()
    today = timezone.localdate()
    seen_today = (QueueTicket.objects.filter(queue_date=today)
                  .exclude(status__in=[QueueTicket.Status.CANCELLED, QueueTicket.Status.EXPIRED]))

    week = acc.week_roster(acc.week_start(today), viewed_by=request.user)
    for day in week:
        day["no_doctor"] = [s for s, shifts in day["sessions"].items()
                            if not day["is_past"] and not any(sh.staff.role == "DOCTOR" and sh.staff.is_active
                                                              for sh in shifts)]

    return render(request, "accounts/dashboard_admin.html", {
        "name": _staff_name(request.user),
        "stats": {
            "patients_today": seen_today.values("patient_id").distinct().count(),
            "revenue_today": revenue_on(today),
            "revenue_label": f"RM {revenue_on(today):,.2f}",
            "unpaid": Bill.objects.filter(status=Bill.Status.UNPAID).count(),
            "low_stock": low_stock_count(),
        },
        "week": week,
        "recent_bills": _with_totals(Bill.objects.order_by("-created_at")[:8]),
    })
