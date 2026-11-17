"""
billing/views.py
Billing screens (UI.md §5.8). Views stay thin: they call billing/services.py.

Nurses generate bills and record payments; admins void bills and see the sales summary;
patients see their own bills.
"""

import datetime as dt

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render

from accounts.decorators import role_required

from . import services as bs
from .models import Bill

STAFF_ROLES = ("NURSE", "ADMIN")
PAGE_SIZE = 20


def _parse_date(value):
    try:
        return dt.date.fromisoformat((value or "").strip())
    except ValueError:
        return None


def _bill_or_404(pk):
    return get_object_or_404(
        Bill.objects.select_related("consultation__ticket__patient", "consultation__doctor", "created_by"), pk=pk)


# ---------------------------------------------------------------------------
# Retrieve: bill list, bill detail
# ---------------------------------------------------------------------------
@role_required(*STAFF_ROLES)
def bill_list(request):
    status = request.GET.get("status", "all")
    if status not in {k for k, _, _ in bs.STATUS_FILTERS}:
        status = "all"
    query = request.GET.get("q", "").strip()
    day = _parse_date(request.GET.get("date"))

    page_obj = Paginator(bs.list_bills(viewed_by=request.user, status=status, query=query, day=day), PAGE_SIZE) \
        .get_page(request.GET.get("page"))
    bills = bs.with_totals(Bill.objects.filter(pk__in=[b.pk for b in page_obj])
                           .select_related("consultation__ticket__patient").order_by("-created_at"))
    counts = bs.status_counts(query=query, day=day)
    pills = [{"key": k, "label": label, "count": counts[k], "active": k == status} for k, label, _ in bs.STATUS_FILTERS]

    return render(request, "billing/bill_list.html", {
        "bills": bills,
        "page_obj": page_obj,
        "pills": pills,
        "status": status,
        "query": query,
        "day": day,
        "is_nurse": request.user.role == "NURSE",
        "to_bill": list(bs.ready_to_bill()[:10]) if request.user.role == "NURSE" else [],
    })


@login_required
def bill_detail(request, pk):
    bill = _bill_or_404(pk)
    if not bs.can_view(request.user, bill):
        raise PermissionDenied
    items = list(bill.items.order_by("item_type", "description"))
    total = sum((i.line_total for i in items), 0)
    return render(request, "billing/bill_detail.html", {
        "bill": bill,
        "items": items,
        "total": total,
        "change": bs.change_for(bill, total),
        "patient": bill.consultation.ticket.patient,
        "is_patient": request.user.role == "PATIENT",
        "is_nurse": request.user.role == "NURSE",
        "is_admin": request.user.role == "ADMIN",
    })


def _error_text(e):
    return " ".join(getattr(e, "messages", None) or [str(e) or "You don't have permission to do that."])


# ---------------------------------------------------------------------------
# Create: generate a bill from a consultation (nurse)
# ---------------------------------------------------------------------------
@role_required("NURSE")
def bill_create(request, consultation_id):
    from consultation.models import Consultation

    c = get_object_or_404(Consultation.objects.select_related("ticket__patient", "doctor"), pk=consultation_id)
    existing = Bill.objects.filter(consultation=c).first()
    if existing:
        messages.info(request, f"This visit already has bill {existing.bill_no}.")
        return redirect("billing:bill_detail", pk=existing.pk)

    if request.method == "POST":
        try:
            bill = bs.create_bill(created_by=request.user, consultation_id=c.pk)
        except (ValidationError, PermissionDenied) as e:
            messages.error(request, _error_text(e))
            return redirect("billing:bill_create", consultation_id=c.pk)
        messages.success(request, f"Bill {bill.bill_no} created.")
        return redirect("billing:bill_detail", pk=bill.pk)

    lines = bs.bill_lines(c)
    return render(request, "billing/bill_create.html", {
        "c": c,
        "lines": lines,
        "total": sum((line["line_total"] for line in lines), 0),
        "completed": c.ticket.status == "COMPLETED",
    })
