"""
consultation/services.py
Business logic for the Consultation Record module. Views call these functions; keep views thin.

Rules (DESC.md, Module 4):
  - A doctor writes the consultation for a ticket that is with the doctor or completed;
    one consultation per ticket
  - Diagnosis required, consult fee > 0
  - Prescription items: medicine (active, in stock, not expired), dosage, quantity > 0;
    each medicine once; a stock warning if more is prescribed than is in stock
  - Medical certificate (MC): days 1–7, a reason, numbered MC-YYYYMMDD-NNN
  - Only the doctor who wrote it can edit it; once billed, fee and medicines are locked;
    dispensed items can't be changed
  - Delete only if not billed and nothing dispensed (the doctor who wrote it, or an admin)

Errors: ValidationError (message for the user) and PermissionDenied (wrong role).
"""

import datetime as dt
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ObjectDoesNotExist, PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from pharmacy.models import Medicine, PrescriptionItem
from queueing.models import QueueTicket

from .models import Consultation, MedicalCertificate

NOTE_STATUSES = (QueueTicket.Status.IN_CONSULTATION, QueueTicket.Status.COMPLETED)
VIEW_ROLES = {"DOCTOR", "NURSE", "ADMIN"}
MC_MAX_DAYS = 7


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _doctor_of(user):
    """The Staff record of a logged-in doctor, or PermissionDenied."""
    if not user.is_authenticated or user.role != "DOCTOR":
        raise PermissionDenied("Only doctors can write consultations.")
    try:
        return user.staff
    except ObjectDoesNotExist:
        raise PermissionDenied("Your account has no staff record. Please ask the admin.")


def _require_viewer(user):
    if not user.is_authenticated or user.role not in VIEW_ROLES:
        raise PermissionDenied("Only clinic staff can view consultations.")


def is_billed(consultation):
    from billing.models import Bill

    return Bill.objects.filter(consultation=consultation).exists()


def has_dispensed(consultation):
    return consultation.prescription_items.filter(dispensed=True).exists()


def get_mc(consultation):
    try:
        return consultation.medical_certificate
    except ObjectDoesNotExist:
        return None


def mc_end_date(mc):
    """Last day of MC leave (calculated, not stored)."""
    return mc.start_date + dt.timedelta(days=mc.days - 1)


def medicine_problem(medicine, today=None):
    """Why a medicine can't be prescribed now, or None."""
    today = today or timezone.localdate()
    if not medicine.is_active:
        return "no longer stocked"
    if medicine.expiry_date <= today:
        return "expired"
    if medicine.quantity <= 0:
        return "out of stock"
    return None


def prescribable_medicines():
    """All active medicines by name, each with .problem (None if it can be prescribed)."""
    today = timezone.localdate()
    meds = list(Medicine.objects.filter(is_active=True).order_by("name"))
    for m in meds:
        m.problem = medicine_problem(m, today)
    return meds


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def _clean_fields(*, symptoms, diagnosis, notes, consult_fee):
    errors = {}
    symptoms = (symptoms or "").strip()
    diagnosis = " ".join((diagnosis or "").split())
    notes = (notes or "").strip() or None
    if not symptoms:
        errors["symptoms"] = "Symptoms are required."
    if not diagnosis:
        errors["diagnosis"] = "Diagnosis is required."
    elif len(diagnosis) > 255:
        errors["diagnosis"] = "Diagnosis must be at most 255 characters."
    try:
        fee = Decimal(str(consult_fee)).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError):
        fee = None
    if fee is None:
        errors["consult_fee"] = "Enter the consultation fee, e.g. 30.00."
    elif fee <= 0:
        errors["consult_fee"] = "Consultation fee must be more than RM 0."
    elif fee >= Decimal("1000000"):
        errors["consult_fee"] = "Consultation fee is too large."
    return errors, {"symptoms": symptoms, "diagnosis": diagnosis, "notes": notes, "consult_fee": fee}


def _clean_items(items, *, locked=None):
    """Check prescription rows. Returns (errors, cleaned rows, stock warnings).

    `items` is a list of {"medicine": id, "dosage": str, "quantity": int}.
    `locked` maps medicine_id -> already-dispensed PrescriptionItem (must stay unchanged).
    """
    locked = locked or {}
    errors, cleaned, warnings, seen = [], [], [], set()
    medicines = Medicine.objects.in_bulk([i.get("medicine") for i in items if i.get("medicine")])
    for n, item in enumerate(items, start=1):
        med = medicines.get(int(item["medicine"])) if str(item.get("medicine") or "").isdigit() else None
        dosage = " ".join((item.get("dosage") or "").split())
        try:
            qty = int(item.get("quantity"))
        except (TypeError, ValueError):
            qty = 0
        if med is None:
            errors.append(f"Row {n}: choose a medicine.")
            continue
        if med.pk in seen:
            errors.append(f"Row {n}: {med.name} is already in the prescription.")
            continue
        seen.add(med.pk)
        if med.pk in locked:  # dispensed: keep exactly as it was
            old = locked[med.pk]
            if qty != old.quantity or dosage != old.dosage:
                errors.append(f"{med.name} was already dispensed and can't be changed.")
            continue
        problem = medicine_problem(med)
        if problem:
            errors.append(f"{med.name} is {problem} and can't be prescribed.")
        if not dosage:
            errors.append(f"Row {n}: enter the dosage for {med.name}.")
        elif len(dosage) > 100:
            errors.append(f"Row {n}: dosage must be at most 100 characters.")
        if qty <= 0:
            errors.append(f"Row {n}: quantity for {med.name} must be more than 0.")
        elif not problem and qty > med.quantity:
            warnings.append(f"Only {med.quantity} {med.unit} of {med.name} in stock (prescribed {qty}). "
                            "The pharmacy may need to restock before dispensing.")
        cleaned.append({"medicine": med, "dosage": dosage, "quantity": qty})
    missing = set(locked) - seen
    for med_id in missing:
        errors.append(f"{locked[med_id].medicine.name} was already dispensed and can't be removed.")
    return errors, cleaned, warnings


def _clean_mc(mc, visit_date):
    """mc is None (no MC) or {"start_date": date, "days": int, "reason": str}."""
    if not mc:
        return {}, None
    errors = {}
    start = mc.get("start_date")
    reason = " ".join((mc.get("reason") or "").split())
    try:
        days = int(mc.get("days"))
    except (TypeError, ValueError):
        days = 0
    if not isinstance(start, dt.date):
        errors["mc_start_date"] = "Enter the MC start date."
    elif start < visit_date:
        errors["mc_start_date"] = "The MC can't start before the visit date."
    elif start > visit_date + dt.timedelta(days=7):
        errors["mc_start_date"] = "The MC must start within a week of the visit."
    if not 1 <= days <= MC_MAX_DAYS:
        errors["mc_days"] = f"MC days must be between 1 and {MC_MAX_DAYS}."
    if not reason:
        errors["mc_reason"] = "Enter the reason for the MC."
    elif len(reason) > 255:
        errors["mc_reason"] = "Reason must be at most 255 characters."
    return errors, {"start_date": start, "days": days, "reason": reason}


def _raise(field_errors, row_errors):
    if row_errors:
        field_errors["items"] = row_errors
    if field_errors:
        raise ValidationError(field_errors)


# ---------------------------------------------------------------------------
# Saving prescriptions and MCs
# ---------------------------------------------------------------------------
def _save_items(consultation, cleaned):
    """Replace the not-yet-dispensed items with `cleaned` (dispensed ones are kept)."""
    consultation.prescription_items.filter(dispensed=False).delete()
    for row in cleaned:
        PrescriptionItem.objects.create(consultation=consultation, medicine=row["medicine"],
                                        dosage=row["dosage"], quantity=row["quantity"])


def _next_mc_no(day):
    prefix = f"MC-{day:%Y%m%d}-"
    last = (MedicalCertificate.objects.filter(mc_no__startswith=prefix)
            .order_by("-mc_no").values_list("mc_no", flat=True).first())
    n = int(last.rsplit("-", 1)[1]) + 1 if last else 1
    return f"{prefix}{n:03d}"


def _save_mc(consultation, mc):
    existing = get_mc(consultation)
    if mc is None:
        if existing:
            existing.delete()
        return None
    if existing:
        existing.start_date, existing.days, existing.reason = mc["start_date"], mc["days"], mc["reason"]
        existing.save(update_fields=["start_date", "days", "reason"])
        return existing
    for _ in range(5):  # a number taken at the same moment -> try the next one
        try:
            with transaction.atomic():
                return MedicalCertificate.objects.create(
                    mc_no=_next_mc_no(timezone.localdate()), consultation=consultation, **mc)
        except IntegrityError:
            continue
    raise ValidationError("Couldn't number the MC. Please save again.")


# ---------------------------------------------------------------------------
# Create / update / delete
# ---------------------------------------------------------------------------
@transaction.atomic
def create_consultation(*, doctor_user, ticket_id, symptoms, diagnosis, consult_fee,
                        notes=None, items=(), mc=None):
    """Record a visit for a ticket. Returns (consultation, stock warnings)."""
    doctor = _doctor_of(doctor_user)
    try:
        ticket = QueueTicket.objects.select_for_update().get(pk=ticket_id)
    except QueueTicket.DoesNotExist:
        raise ValidationError("Queue ticket not found.")
    if ticket.status not in NOTE_STATUSES:
        raise ValidationError("Notes can only be written while the patient is with the doctor or after the visit.")
    if Consultation.objects.filter(ticket=ticket).exists():
        raise ValidationError("This visit already has a consultation record. Edit it instead.")

    errors, data = _clean_fields(symptoms=symptoms, diagnosis=diagnosis, notes=notes, consult_fee=consult_fee)
    row_errors, cleaned, warnings = _clean_items(list(items))
    mc_errors, mc_data = _clean_mc(mc, ticket.queue_date)
    errors.update(mc_errors)
    _raise(errors, row_errors)

    consultation = Consultation.objects.create(ticket=ticket, doctor=doctor, **data)
    _save_items(consultation, cleaned)
    _save_mc(consultation, mc_data)
    return consultation, warnings


@transaction.atomic
def update_consultation(*, doctor_user, consultation_id, symptoms, diagnosis, consult_fee,
                        notes=None, items=(), mc=None):
    """Edit a consultation. Returns (consultation, stock warnings)."""
    doctor = _doctor_of(doctor_user)
    try:
        consultation = Consultation.objects.select_for_update().select_related("ticket").get(pk=consultation_id)
    except Consultation.DoesNotExist:
        raise ValidationError("Consultation not found.")
    if consultation.doctor_id != doctor.pk:
        raise PermissionDenied("Only the doctor who wrote this consultation can edit it.")

    errors, data = _clean_fields(symptoms=symptoms, diagnosis=diagnosis, notes=notes, consult_fee=consult_fee)
    billed = is_billed(consultation)
    if billed:
        # The bill was made from the fee and medicines: they can't change now.
        data["consult_fee"] = consultation.consult_fee
        row_errors, cleaned, warnings = [], None, []
    else:
        locked = {i.medicine_id: i for i in consultation.prescription_items.filter(dispensed=True)
                  .select_related("medicine")}
        row_errors, cleaned, warnings = _clean_items(list(items), locked=locked)
    mc_errors, mc_data = _clean_mc(mc, consultation.ticket.queue_date)
    errors.update(mc_errors)
    _raise(errors, row_errors)

    for field, value in data.items():
        setattr(consultation, field, value)
    consultation.save()
    if cleaned is not None:
        _save_items(consultation, cleaned)
    _save_mc(consultation, mc_data)
    return consultation, warnings


def can_delete(consultation):
    return not is_billed(consultation) and not has_dispensed(consultation)


@transaction.atomic
def delete_consultation(*, deleted_by, consultation_id):
    try:
        consultation = Consultation.objects.select_for_update().select_related("doctor").get(pk=consultation_id)
    except Consultation.DoesNotExist:
        raise ValidationError("Consultation not found.")
    is_author = (deleted_by.is_authenticated and deleted_by.role == "DOCTOR"
                 and consultation.doctor.user_id == deleted_by.id)
    if not (is_author or (deleted_by.is_authenticated and deleted_by.role == "ADMIN")):
        raise PermissionDenied("Only the doctor who wrote it, or an admin, can delete a consultation.")
    if is_billed(consultation):
        raise ValidationError("This consultation has been billed and can't be deleted.")
    if has_dispensed(consultation):
        raise ValidationError("Medicines from this consultation were already dispensed, so it can't be deleted.")

    mc = get_mc(consultation)
    if mc:
        mc.delete()
    consultation.prescription_items.all().delete()
    consultation.delete()


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------
def list_consultations(*, viewed_by, query=""):
    """Newest first; search by patient name, IC or diagnosis."""
    _require_viewer(viewed_by)
    qs = (Consultation.objects.select_related("ticket__patient", "doctor")
          .prefetch_related("medical_certificate"))
    query = (query or "").strip()
    if query:
        qs = qs.filter(Q(ticket__patient__full_name__icontains=query) | Q(ticket__patient__ic_no__icontains=query)
                       | Q(diagnosis__icontains=query))
    return qs.order_by("-created_at")


def visits_without_notes(*, doctor_user=None, day=None):
    """Today's tickets that are with the doctor or completed but have no consultation yet."""
    day = day or timezone.localdate()
    tickets = (QueueTicket.objects.filter(queue_date=day, status__in=NOTE_STATUSES, consultation__isnull=True)
               .select_related("patient").order_by("queue_no"))
    if doctor_user is not None:
        try:
            tickets = tickets.filter(doctor=doctor_user.staff)
        except ObjectDoesNotExist:
            return tickets.none()
    return tickets


def consultation_total(consultation):
    """Fee + medicines at today's prices (what the bill will be based on)."""
    meds = sum((i.quantity * i.medicine.unit_price for i in consultation.prescription_items.all()), Decimal("0"))
    return consultation.consult_fee + meds
