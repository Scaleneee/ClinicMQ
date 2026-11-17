"""
consultation/views.py
Consultation Record screens (UI.md §5.6). Views stay thin: they call consultation/services.py.
"""

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render

from accounts.decorators import role_required
from queueing.models import QueueTicket

from . import services as cs
from .forms import ConsultationForm, rows_from_post
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



# ---------------------------------------------------------------------------
# Create / update (doctor)
# ---------------------------------------------------------------------------
SERVICE_FIELDS = {"symptoms", "diagnosis", "notes", "consult_fee", "mc_start_date", "mc_days", "mc_reason"}


def _show_errors(form, error):
    """Field errors go under their fields; prescription row errors are returned as a list."""
    item_errors = []
    if hasattr(error, "error_dict"):
        for field, field_messages in error.message_dict.items():
            if field == "items":
                item_errors.extend(field_messages)
            else:
                for message in field_messages:
                    form.add_error(field if field in SERVICE_FIELDS else None, message)
    else:
        for message in error.messages:
            form.add_error(None, message)
    return item_errors


def _after_save(request, consultation, warnings, verb):
    messages.success(request, f"Consultation {verb}.")
    for w in warnings:
        messages.warning(request, w)
    if request.POST.get("next") == "console":
        return redirect("queueing:console")
    return redirect("consultation:detail", pk=consultation.pk)


def _form_page(request, *, form, ticket, consultation, rows, item_errors, locked_ids=(), billed=False):
    return render(request, "consultation/consultation_form.html", {
        "form": form,
        "ticket": ticket,
        "patient": ticket.patient,
        "c": consultation,
        "rows": rows,
        "item_errors": item_errors,
        "locked_ids": set(locked_ids),
        "billed": billed,
        "medicines": cs.prescribable_medicines(),
        "next": request.GET.get("next") or request.POST.get("next") or "",
    })


@role_required("DOCTOR")
def consultation_create(request, ticket_id):
    ticket = get_object_or_404(QueueTicket.objects.select_related("patient"), pk=ticket_id)
    existing = Consultation.objects.filter(ticket=ticket).first()
    if existing:
        return redirect("consultation:edit", pk=existing.pk)

    form = ConsultationForm(request.POST or None, initial={"mc_start_date": ticket.queue_date, "mc_days": 1})
    rows = rows_from_post(request.POST) if request.method == "POST" else []
    item_errors = []
    if request.method == "POST" and form.is_valid():
        try:
            c, warnings = cs.create_consultation(doctor_user=request.user, ticket_id=ticket.pk, items=rows,
                                                 mc=form.mc(), **form.fields_for_service())
        except ValidationError as e:
            item_errors = _show_errors(form, e)
        except PermissionDenied as e:
            messages.error(request, str(e))
        else:
            return _after_save(request, c, warnings, "saved")
    return _form_page(request, form=form, ticket=ticket, consultation=None, rows=rows, item_errors=item_errors)


@role_required("DOCTOR")
def consultation_edit(request, pk):
    c = get_object_or_404(Consultation.objects.select_related("ticket__patient", "doctor"), pk=pk)
    if c.doctor.user_id != request.user.id:
        messages.error(request, "Only the doctor who wrote this consultation can edit it.")
        return redirect("consultation:detail", pk=c.pk)

    mc = cs.get_mc(c)
    items = list(c.prescription_items.select_related("medicine"))
    initial = {"symptoms": c.symptoms, "diagnosis": c.diagnosis, "notes": c.notes, "consult_fee": c.consult_fee,
               "issue_mc": mc is not None,
               "mc_start_date": mc.start_date if mc else c.ticket.queue_date,
               "mc_days": mc.days if mc else 1, "mc_reason": mc.reason if mc else ""}
    form = ConsultationForm(request.POST or None, initial=initial)
    billed = cs.is_billed(c)
    if request.method == "POST":
        rows = rows_from_post(request.POST)
    else:
        rows = [{"medicine": str(i.medicine_id), "dosage": i.dosage, "quantity": str(i.quantity)} for i in items]
    item_errors = []

    if request.method == "POST" and form.is_valid():
        try:
            c, warnings = cs.update_consultation(doctor_user=request.user, consultation_id=c.pk, items=rows,
                                                 mc=form.mc(), **form.fields_for_service())
        except ValidationError as e:
            item_errors = _show_errors(form, e)
        except PermissionDenied as e:
            messages.error(request, str(e))
        else:
            return _after_save(request, c, warnings, "updated")
    return _form_page(request, form=form, ticket=c.ticket, consultation=c, rows=rows, item_errors=item_errors,
                      locked_ids={str(i.medicine_id) for i in items if i.dispensed}, billed=billed)


# ---------------------------------------------------------------------------
# Delete (the doctor who wrote it, or an admin) - blocked once billed or dispensed
# ---------------------------------------------------------------------------
@role_required("DOCTOR", "ADMIN")
def consultation_delete(request, pk):
    c = get_object_or_404(Consultation.objects.select_related("ticket__patient", "doctor"), pk=pk)
    if request.method == "POST":
        done = _run(request, lambda: cs.delete_consultation(deleted_by=request.user, consultation_id=c.pk) or True,
                    f"The consultation for {c.ticket.patient.full_name.title()} was deleted.")
        if done:
            return redirect("consultation:list")
        return redirect("consultation:delete", pk=c.pk)

    blocked = None
    if cs.is_billed(c):
        blocked = "This consultation has been billed and can't be deleted."
    elif cs.has_dispensed(c):
        blocked = "Medicines from this consultation were already dispensed, so it can't be deleted."
    elif request.user.role == "DOCTOR" and c.doctor.user_id != request.user.id:
        blocked = "Only the doctor who wrote it, or an admin, can delete a consultation."
    return render(request, "consultation/consultation_confirm_delete.html", {
        "c": c, "mc": cs.get_mc(c), "blocked": blocked,
    })
