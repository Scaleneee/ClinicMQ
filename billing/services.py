"""
billing/services.py
Business logic for the Billing module (DESC.md, Module 6). Views call these functions; keep views thin.

Rules:
  - A nurse generates the bill from a completed visit: consultation fee + prescribed medicines.
    Medicine prices are copied onto the bill (historical price). One bill per consultation.
  - Bill numbers look like B-YYYYMMDD-NNN
  - Total = consultation fee + medicines (no discount or tax); calculated, never stored
  - Record payment (nurse): the method is required (Cash, Card or E-wallet);
    cash needs amount received >= total and the change is calculated; card and e-wallet pay the total
  - Void (admin): a reason is required; a void bill takes no payment
  - Patients only see their own bills

Errors: ValidationError (message for the user) and PermissionDenied (wrong role).
"""

import datetime as dt
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ObjectDoesNotExist, PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Count, DecimalField, ExpressionWrapper, F, Q, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone

from queueing.models import QueueTicket

from .models import Bill, BillItem

STAFF_ROLES = {"NURSE", "ADMIN"}
MAX_AMOUNT = Decimal("1000000")  # amount_paid has 8 digits, 2 after the point
MAX_SUMMARY_DAYS = 366

STATUS_FILTERS = [  # (key, label, status) for the filter pills
    ("all", "All", None),
    ("unpaid", "Unpaid", Bill.Status.UNPAID),
    ("paid", "Paid", Bill.Status.PAID),
    ("void", "Void", Bill.Status.VOID),
]

LINE_TOTAL = ExpressionWrapper(F("quantity") * F("unit_price"),
                               output_field=DecimalField(max_digits=12, decimal_places=2))


# ---------------------------------------------------------------------------
# Permissions
# ---------------------------------------------------------------------------
def _nurse_of(user, action):
    if not user.is_authenticated or user.role != "NURSE":
        raise PermissionDenied(f"Only nurses can {action}.")
    try:
        return user.staff
    except ObjectDoesNotExist:
        raise PermissionDenied("Your account has no staff record. Please ask the admin.")


def _require_staff(user):
    if not user.is_authenticated or user.role not in STAFF_ROLES:
        raise PermissionDenied("Only nurses and admins can see the bills.")


def is_owner(user, bill):
    """True if `user` is the patient the bill belongs to."""
    return (user.is_authenticated and user.role == "PATIENT"
            and bill.consultation.ticket.patient.user_id == user.id)


def can_view(user, bill):
    return user.is_authenticated and (user.role in STAFF_ROLES or is_owner(user, bill))


# ---------------------------------------------------------------------------
# Totals
# ---------------------------------------------------------------------------
def with_totals(bills):
    """List of bills, each with .total_amount, using one query for all the items."""
    bills = list(bills.prefetch_related("items"))
    for b in bills:
        b.total_amount = sum((i.line_total for i in b.items.all()), Decimal("0"))
    return bills


def change_for(bill, total=None):
    """Change given back for a cash payment, else None."""
    if bill.payment_method != Bill.PaymentMethod.CASH or bill.amount_paid is None:
        return None
    return bill.amount_paid - (bill.total if total is None else total)


# ---------------------------------------------------------------------------
# Generate a bill
# ---------------------------------------------------------------------------
def ready_to_bill():
    """Completed visits with a consultation but no bill yet, oldest first."""
    from consultation.models import Consultation

    return (Consultation.objects
            .filter(ticket__status=QueueTicket.Status.COMPLETED, bill__isnull=True)
            .select_related("ticket__patient", "doctor")
            .order_by("ticket__completed_at", "created_at"))


def bill_lines(consultation):
    """What the bill will contain: the fee first, then each medicine at today's price."""
    lines = [{"item_type": BillItem.ItemType.CONSULTATION, "medicine": None,
              "description": "Consultation fee", "quantity": 1, "unit_price": consultation.consult_fee}]
    for item in consultation.prescription_items.select_related("medicine").order_by("medicine__name"):
        lines.append({"item_type": BillItem.ItemType.MEDICINE, "medicine": item.medicine,
                      "description": item.medicine.name, "quantity": item.quantity,
                      "unit_price": item.medicine.unit_price})
    for line in lines:
        line["line_total"] = line["quantity"] * line["unit_price"]
    return lines


def _next_bill_no(day):
    prefix = f"B-{day:%Y%m%d}-"
    last = (Bill.objects.filter(bill_no__startswith=prefix)
            .order_by("-bill_no").values_list("bill_no", flat=True).first())
    n = int(last.rsplit("-", 1)[1]) + 1 if last else 1
    return f"{prefix}{n:03d}"


@transaction.atomic
def create_bill(*, created_by, consultation_id):
    """Generate the bill for a consultation. Returns the Bill."""
    from consultation.models import Consultation

    nurse = _nurse_of(created_by, "generate bills")
    try:
        consultation = Consultation.objects.select_for_update().select_related("ticket").get(pk=consultation_id)
    except Consultation.DoesNotExist:
        raise ValidationError("Consultation not found.")
    if consultation.ticket.status != QueueTicket.Status.COMPLETED:
        raise ValidationError("The visit isn't completed yet. Bill it after the patient has seen the doctor.")
    existing = Bill.objects.filter(consultation=consultation).first()
    if existing:
        raise ValidationError(f"This visit already has a bill ({existing.bill_no}).")

    lines = bill_lines(consultation)
    for _ in range(5):  # a number taken at the same moment -> try the next one
        try:
            with transaction.atomic():
                bill = Bill.objects.create(bill_no=_next_bill_no(timezone.localdate()),
                                           consultation=consultation, created_by=nurse)
                break
        except IntegrityError:
            if Bill.objects.filter(consultation=consultation).exists():
                raise ValidationError("This visit was billed a moment ago.")
    else:
        raise ValidationError("Couldn't number the bill. Please try again.")

    BillItem.objects.bulk_create([
        BillItem(bill=bill, item_type=l["item_type"], medicine=l["medicine"], description=l["description"],
                 quantity=l["quantity"], unit_price=l["unit_price"]) for l in lines])
    return bill


# ---------------------------------------------------------------------------
# Record payment / void
# ---------------------------------------------------------------------------
def _get_for_update(bill_id):
    try:
        return Bill.objects.select_for_update().get(pk=bill_id)
    except Bill.DoesNotExist:
        raise ValidationError("Bill not found.")


@transaction.atomic
def record_payment(*, recorded_by, bill_id, method, amount_received=None):
    """Mark an unpaid bill as paid. Returns the Bill."""
    _nurse_of(recorded_by, "record payments")
    bill = _get_for_update(bill_id)
    if bill.status == Bill.Status.VOID:
        raise ValidationError("This bill is void, so no payment can be recorded.")
    if bill.status == Bill.Status.PAID:
        raise ValidationError("This bill is already paid.")

    total = bill.total
    errors = {}
    if method not in Bill.PaymentMethod.values:
        errors["method"] = "Choose how the patient paid."
    amount = total
    if method == Bill.PaymentMethod.CASH:
        try:
            amount = Decimal(str(amount_received).strip()).quantize(Decimal("0.01"))
        except (InvalidOperation, TypeError, ValueError):
            amount = None
        if amount is None:
            errors["amount_received"] = "Enter the amount received, e.g. 50.00."
        elif amount < total:
            errors["amount_received"] = "Amount paid is less than the total."
        elif amount >= MAX_AMOUNT:
            errors["amount_received"] = "Amount is too large."
    if errors:
        raise ValidationError(errors)

    bill.status = Bill.Status.PAID
    bill.payment_method = method
    bill.amount_paid = amount
    bill.paid_at = timezone.now()
    bill.save(update_fields=["status", "payment_method", "amount_paid", "paid_at"])
    return bill


@transaction.atomic
def void_bill(*, voided_by, bill_id, reason):
    """Void a bill with a reason (admin). Returns the Bill."""
    if not voided_by.is_authenticated or voided_by.role != "ADMIN":
        raise PermissionDenied("Only admins can void bills.")
    bill = _get_for_update(bill_id)
    if bill.status == Bill.Status.VOID:
        raise ValidationError("This bill is already void.")
    reason = " ".join((reason or "").split())
    if not reason:
        raise ValidationError({"reason": "Enter the reason for voiding this bill."})
    if len(reason) > 255:
        raise ValidationError({"reason": "Reason must be at most 255 characters."})
    bill.status = Bill.Status.VOID
    bill.void_reason = reason
    bill.save(update_fields=["status", "void_reason"])
    return bill


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------
def _search(qs, query):
    query = (query or "").strip()
    if query:
        qs = qs.filter(Q(bill_no__icontains=query) | Q(consultation__ticket__patient__full_name__icontains=query)
                       | Q(consultation__ticket__patient__ic_no__icontains=query))
    return qs


def list_bills(*, viewed_by, status="all", query="", day=None):
    """Newest first; filter by status pill, search (bill no., patient name or IC) and date."""
    _require_staff(viewed_by)
    qs = _search(Bill.objects.select_related("consultation__ticket__patient"), query)
    if day:
        qs = qs.filter(created_at__date=day)
    wanted = dict((k, s) for k, _, s in STATUS_FILTERS).get(status)
    if wanted:
        qs = qs.filter(status=wanted)
    return qs.order_by("-created_at")


def status_counts(*, query="", day=None):
    qs = _search(Bill.objects.all(), query)
    if day:
        qs = qs.filter(created_at__date=day)
    return qs.aggregate(**{key: Count("pk", filter=Q(status=s) if s else Q()) for key, _, s in STATUS_FILTERS})


def bills_for_patient(user):
    """The patient's own bills, newest first (none if the account has no patient record)."""
    return (Bill.objects.filter(consultation__ticket__patient__user=user)
            .select_related("consultation__ticket__patient", "consultation__doctor")
            .order_by("-created_at"))


# ---------------------------------------------------------------------------
# Daily sales summary (admin)
# ---------------------------------------------------------------------------
def sales_summary(*, viewed_by, start, end):
    """Paid bills between start and end (by payment date, both days included)."""
    if not viewed_by.is_authenticated or viewed_by.role != "ADMIN":
        raise PermissionDenied("Only admins can see the sales summary.")
    if start > end:
        raise ValidationError("The start date must be on or before the end date.")
    if (end - start).days >= MAX_SUMMARY_DAYS:
        raise ValidationError("Choose a range of one year or less.")

    paid_items = BillItem.objects.filter(bill__status=Bill.Status.PAID,
                                         bill__paid_at__date__gte=start, bill__paid_at__date__lte=end)
    paid_bills = Bill.objects.filter(status=Bill.Status.PAID, paid_at__date__gte=start, paid_at__date__lte=end)

    revenue = paid_items.aggregate(total=Sum(LINE_TOTAL))["total"] or Decimal("0")
    paid_count = paid_bills.count()

    per_day = {row["day"]: row for row in (
        paid_items.annotate(day=TruncDate("bill__paid_at")).values("day")
        .annotate(revenue=Sum(LINE_TOTAL), bills=Count("bill", distinct=True)))}
    days = []
    d = start
    while d <= end:
        row = per_day.get(d)
        days.append({"date": d, "bills": row["bills"] if row else 0,
                     "revenue": row["revenue"] if row else Decimal("0")})
        d += dt.timedelta(days=1)

    labels = dict(Bill.PaymentMethod.choices)
    by_method = []
    for row in (paid_items.values("bill__payment_method")
                .annotate(revenue=Sum(LINE_TOTAL), bills=Count("bill", distinct=True)).order_by("-revenue")):
        by_method.append({"method": labels.get(row["bill__payment_method"], "–"),
                          "bills": row["bills"], "revenue": row["revenue"],
                          "share": round(row["revenue"] / revenue * 100) if revenue else 0})

    top_medicines = list(
        paid_items.filter(item_type=BillItem.ItemType.MEDICINE)
        .values("description").annotate(sold=Sum("quantity"), revenue=Sum(LINE_TOTAL))
        .order_by("-sold", "description")[:5])

    return {
        "revenue": revenue,
        "paid_count": paid_count,
        "average": (revenue / paid_count).quantize(Decimal("0.01")) if paid_count else None,
        "void_count": Bill.objects.filter(status=Bill.Status.VOID, created_at__date__gte=start,
                                          created_at__date__lte=end).count(),
        "days": days,
        "by_method": by_method,
        "top_medicines": top_medicines,
    }
