"""
pharmacy/services.py
Business logic for the Medicine Inventory module (DESC.md, Module 5). Views call these functions; keep views thin.

Rules:
  - Only nurses add, edit, restock and dispense; only admins delete; all staff can view
  - Unique name (ignoring case), unit price > 0, quantity >= 0, reorder level >= 0,
    expiry date in the future
  - Restock adds to the stock; the new expiry date is optional, but needed once the stock has expired
  - A medicine that was ever prescribed can't be deleted (its history must stay)
  - Dispense: the stock goes down automatically and the nurse and time are logged;
    never more than is in stock, never an expired medicine, and each prescription item only once

Errors: ValidationError (message for the user) and PermissionDenied (wrong role).
"""

import datetime as dt
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ObjectDoesNotExist, PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Count, F, Q
from django.utils import timezone

from queueing.models import QueueTicket

from .models import Medicine, PrescriptionItem

EXPIRING_DAYS = 30            # "Expiring soon" = expires within this many days
MAX_PRICE = Decimal("100000")  # sanity limits for typing mistakes
MAX_QUANTITY = 1_000_000
VIEW_ROLES = {"NURSE", "DOCTOR", "ADMIN"}

FILTERS = [  # (key, label) for the filter pills
    ("all", "All"),
    ("low", "Low stock"),
    ("expiring", "Expiring soon"),
    ("out", "Out of stock"),
]


# ---------------------------------------------------------------------------
# Permissions
# ---------------------------------------------------------------------------
def _nurse_of(user, action="manage medicines"):
    """The Staff record of a logged-in nurse, or PermissionDenied."""
    if not user.is_authenticated or user.role != "NURSE":
        raise PermissionDenied(f"Only nurses can {action}.")
    try:
        return user.staff
    except ObjectDoesNotExist:
        raise PermissionDenied("Your account has no staff record. Please ask the admin.")


def _require_viewer(user):
    if not user.is_authenticated or user.role not in VIEW_ROLES:
        raise PermissionDenied("Only clinic staff can view the medicine inventory.")


# ---------------------------------------------------------------------------
# Badges and filters
# ---------------------------------------------------------------------------
def soon_date(today=None):
    return (today or timezone.localdate()) + dt.timedelta(days=EXPIRING_DAYS)


def stock_badges(medicine, today=None):
    """[(label, badge style), ...] for a medicine: stock first, then expiry."""
    today = today or timezone.localdate()
    badges = []
    if medicine.quantity == 0:
        badges.append(("Out of stock", "out"))
    elif medicine.quantity <= medicine.reorder_level:
        badges.append(("Low stock", "waiting"))
    if medicine.expiry_date <= today:
        badges.append(("Expired", "out"))
    elif medicine.expiry_date <= soon_date(today):
        badges.append(("Expiring soon", "missed"))
    return badges


def _filter_q(key, today):
    return {
        "low": Q(quantity__lte=F("reorder_level")),       # includes out of stock
        "expiring": Q(expiry_date__lte=soon_date(today)),  # includes expired
        "out": Q(quantity=0),
    }.get(key, Q())


def list_medicines(*, viewed_by, query="", category="", status="all"):
    """Active medicines by name, filtered. Each gets .badges."""
    _require_viewer(viewed_by)
    today = timezone.localdate()
    qs = Medicine.objects.filter(is_active=True)
    query = (query or "").strip()
    if query:
        qs = qs.filter(Q(name__icontains=query) | Q(category__icontains=query))
    if category:
        qs = qs.filter(category__iexact=category)
    return qs.filter(_filter_q(status, today)).order_by("name")


def filter_counts(*, query="", category=""):
    """How many medicines each filter pill would show (with the same search and category)."""
    today = timezone.localdate()
    qs = Medicine.objects.filter(is_active=True)
    if query:
        qs = qs.filter(Q(name__icontains=query) | Q(category__icontains=query))
    if category:
        qs = qs.filter(category__iexact=category)
    return qs.aggregate(**{key: Count("pk", filter=_filter_q(key, today)) for key, _ in FILTERS})


def categories():
    return list(Medicine.objects.filter(is_active=True).order_by("category")
                .values_list("category", flat=True).distinct())


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def _as_int(value):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _clean(data, *, medicine=None):
    """Check the medicine fields. Returns (errors, cleaned data)."""
    errors = {}
    today = timezone.localdate()
    name = " ".join((data.get("name") or "").split())
    category = " ".join((data.get("category") or "").split())
    unit = " ".join((data.get("unit") or "").split())

    if not name:
        errors["name"] = "Name is required."
    elif len(name) > 100:
        errors["name"] = "Name must be at most 100 characters."
    else:
        same = Medicine.objects.filter(name__iexact=name)
        if medicine is not None:
            same = same.exclude(pk=medicine.pk)
        if same.exists():
            errors["name"] = f"{name} is already in the inventory."
    if not category:
        errors["category"] = "Category is required."
    elif len(category) > 50:
        errors["category"] = "Category must be at most 50 characters."
    if not unit:
        errors["unit"] = "Unit is required, e.g. tablets or bottles."
    elif len(unit) > 20:
        errors["unit"] = "Unit must be at most 20 characters."

    try:
        price = Decimal(str(data.get("unit_price"))).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError):
        price = None
    if price is None:
        errors["unit_price"] = "Enter the unit price, e.g. 0.50."
    elif price <= 0:
        errors["unit_price"] = "Unit price must be more than RM 0."
    elif price >= MAX_PRICE:
        errors["unit_price"] = "Unit price is too large."

    quantity = _as_int(data.get("quantity"))
    if quantity is None:
        errors["quantity"] = "Enter the quantity in stock."
    elif quantity < 0:
        errors["quantity"] = "Quantity can't be negative."
    elif quantity > MAX_QUANTITY:
        errors["quantity"] = "Quantity is too large."

    reorder = _as_int(data.get("reorder_level"))
    if reorder is None:
        errors["reorder_level"] = "Enter the reorder level."
    elif reorder < 0:
        errors["reorder_level"] = "Reorder level can't be negative."
    elif reorder > MAX_QUANTITY:
        errors["reorder_level"] = "Reorder level is too large."

    expiry = data.get("expiry_date")
    unchanged = medicine is not None and expiry == medicine.expiry_date
    if not isinstance(expiry, dt.date):
        errors["expiry_date"] = "Enter the expiry date."
    elif expiry <= today and not unchanged:  # an old date can stay while editing other fields
        errors["expiry_date"] = "Expiry date must be in the future."

    return errors, {"name": name, "category": category, "unit": unit, "unit_price": price,
                    "quantity": quantity, "reorder_level": reorder, "expiry_date": expiry}


# ---------------------------------------------------------------------------
# Create / update / restock / delete
# ---------------------------------------------------------------------------
def create_medicine(*, created_by, **data):
    _nurse_of(created_by, "add medicines")
    errors, cleaned = _clean(data)
    if errors:
        raise ValidationError(errors)
    return Medicine.objects.create(**cleaned)


def _get_for_update(medicine_id):
    try:
        return Medicine.objects.select_for_update().get(pk=medicine_id, is_active=True)
    except Medicine.DoesNotExist:
        raise ValidationError("Medicine not found.")


@transaction.atomic
def update_medicine(*, updated_by, medicine_id, **data):
    _nurse_of(updated_by, "edit medicines")
    medicine = _get_for_update(medicine_id)
    errors, cleaned = _clean(data, medicine=medicine)
    if errors:
        raise ValidationError(errors)
    for field, value in cleaned.items():
        setattr(medicine, field, value)
    medicine.save()
    return medicine


@transaction.atomic
def restock_medicine(*, restocked_by, medicine_id, add_quantity, expiry_date=None):
    """Add new stock. A new expiry date replaces the old one (needed if the stock has expired)."""
    _nurse_of(restocked_by, "restock medicines")
    medicine = _get_for_update(medicine_id)
    today = timezone.localdate()
    errors = {}
    added = _as_int(add_quantity)
    if added is None or added <= 0:
        errors["add_quantity"] = "Enter how many to add (more than 0)."
    elif medicine.quantity + added > MAX_QUANTITY:
        errors["add_quantity"] = "That's more stock than the system allows."
    if expiry_date:
        if expiry_date <= today:
            errors["expiry_date"] = "Expiry date must be in the future."
    elif medicine.expiry_date <= today:
        errors["expiry_date"] = "The current stock has expired. Enter the new stock's expiry date."
    if errors:
        raise ValidationError(errors)

    medicine.quantity += added
    if expiry_date:
        medicine.expiry_date = expiry_date
    medicine.save(update_fields=["quantity", "expiry_date"])
    return medicine


def delete_blocked_reason(medicine):
    """Why the medicine can't be deleted, or None."""
    if medicine.prescription_items.exists() or medicine.bill_items.exists():
        return "Used in prescriptions. It must stay so that past visits and bills stay correct."
    return None


@transaction.atomic
def delete_medicine(*, deleted_by, medicine_id):
    if not deleted_by.is_authenticated or deleted_by.role != "ADMIN":
        raise PermissionDenied("Only admins can delete medicines.")
    medicine = _get_for_update(medicine_id)
    reason = delete_blocked_reason(medicine)
    if reason:
        raise ValidationError(reason)
    name = medicine.name
    medicine.delete()
    return name


# ---------------------------------------------------------------------------
# Dispense
# ---------------------------------------------------------------------------
def pending_dispense():
    """Completed visits with medicines not dispensed yet, oldest first."""
    from consultation.models import Consultation

    return (Consultation.objects
            .filter(prescription_items__dispensed=False, ticket__status=QueueTicket.Status.COMPLETED)
            .distinct()
            .select_related("ticket__patient", "doctor")
            .order_by("ticket__completed_at", "created_at"))


def item_problem(item, today=None):
    """Why a prescription item can't be dispensed now, or None."""
    today = today or timezone.localdate()
    med = item.medicine
    if item.dispensed:
        return f"{med.name} was already dispensed."
    if med.expiry_date <= today:
        return f"{med.name} has expired and can't be dispensed. Restock it with new stock first."
    if item.quantity > med.quantity:
        return f"Not enough stock for {med.name} (need {item.quantity}, have {med.quantity})."
    return None


@transaction.atomic
def dispense_items(*, dispensed_by, consultation_id, medicine_ids):
    """Dispense the chosen prescription items of a visit. All or nothing.

    Returns the list of dispensed PrescriptionItems.
    """
    from consultation.models import Consultation

    nurse = _nurse_of(dispensed_by, "dispense medicines")
    try:
        consultation = Consultation.objects.select_related("ticket").get(pk=consultation_id)
    except Consultation.DoesNotExist:
        raise ValidationError("Consultation not found.")
    if consultation.ticket.status != QueueTicket.Status.COMPLETED:
        raise ValidationError("Medicines are dispensed after the visit is completed.")

    wanted = {_as_int(m) for m in medicine_ids} - {None}
    if not wanted:
        raise ValidationError("Tick at least one medicine to dispense.")

    # Lock the medicines so two nurses can't take the same stock at once.
    medicines = Medicine.objects.select_for_update().in_bulk(sorted(wanted))
    items = list(PrescriptionItem.objects.filter(consultation=consultation, medicine_id__in=wanted))
    if len(items) != len(wanted):
        raise ValidationError("Some of those medicines aren't in this prescription. Reload the page and try again.")

    today = timezone.localdate()
    for item in items:
        item.medicine = medicines[item.medicine_id]
    problems = [p for p in (item_problem(i, today) for i in items) if p]
    if problems:
        raise ValidationError(problems)

    now = timezone.now()
    for item in items:
        med = item.medicine
        med.quantity -= item.quantity
        med.save(update_fields=["quantity"])
        PrescriptionItem.objects.filter(consultation=consultation, medicine=med, dispensed=False).update(
            dispensed=True, dispensed_at=now, dispensed_by=nurse)
        item.dispensed, item.dispensed_at, item.dispensed_by = True, now, nurse
    return items
