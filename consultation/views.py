"""
consultation/views.py
Consultation Record screens (UI.md §5.6). Views stay thin: they call consultation/services.py.
"""

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render

from accounts.decorators import role_required

from . import services as cs
from .models import Consultation

VIEW_ROLES = ("DOCTOR", "NURSE", "ADMIN")
PAGE_SIZE = 20


def _bill_of(consultation):
    from billing.models import Bill

    return Bill.objects.filter(consultation=consultation).first()


# ---------------------------------------------------------------------------
# Retrieve: list, detail
# ---------------------------------------------------------------------------
@role_required(*VIEW_ROLES)
def consultation_list(request):
    from billing.models import Bill

    query = request.GET.get("q", "").strip()
    page_obj = Paginator(cs.list_consultations(viewed_by=request.user, query=query), PAGE_SIZE) \
        .get_page(request.GET.get("page"))
    billed_ids = set(Bill.objects.filter(consultation__in=list(page_obj)).values_list("consultation_id", flat=True))
    for c in page_obj:
        c.mc = cs.get_mc(c)
        c.billed = c.pk in billed_ids

    return render(request, "consultation/consultation_list.html", {
        "page_obj": page_obj,
        "query": query,
        "needs_notes": cs.visits_without_notes(doctor_user=request.user) if request.user.role == "DOCTOR" else [],
    })


@role_required(*VIEW_ROLES)
def consultation_detail(request, pk):
    c = get_object_or_404(
        Consultation.objects.select_related("ticket__patient", "doctor__user"), pk=pk)
    items = list(c.prescription_items.select_related("medicine", "dispensed_by"))
    for i in items:
        i.amount = i.quantity * i.medicine.unit_price
    meds_total = sum((i.amount for i in items), 0)
    is_author = request.user.role == "DOCTOR" and c.doctor.user_id == request.user.id
    mc = cs.get_mc(c)

    return render(request, "consultation/consultation_detail.html", {
        "c": c,
        "items": items,
        "mc": mc,
        "mc_end": cs.mc_end_date(mc) if mc else None,
        "meds_total": meds_total,
        "total": c.consult_fee + meds_total,
        "bill": _bill_of(c),
        "can_edit": is_author,
        "can_delete": (is_author or request.user.role == "ADMIN") and cs.can_delete(c),
    })


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

