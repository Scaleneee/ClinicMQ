from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models


class Bill(models.Model):
    class Status(models.TextChoices):
        UNPAID = "UNPAID", "Unpaid"
        PAID = "PAID", "Paid"
        VOID = "VOID", "Void"

    class PaymentMethod(models.TextChoices):
        CASH = "CASH", "Cash"
        CARD = "CARD", "Card"
        EWALLET = "EWALLET", "E-wallet"

    bill_id = models.BigAutoField(primary_key=True)
    bill_no = models.CharField(max_length=20, unique=True)
    consultation = models.OneToOneField(
        "consultation.Consultation", on_delete=models.PROTECT, related_name="bill"
    )
    discount = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal("0"))
    tax_rate = models.DecimalField(max_digits=4, decimal_places=2, default=Decimal("0"))
    status = models.CharField(max_length=6, choices=Status.choices, default=Status.UNPAID)
    payment_method = models.CharField(
        max_length=10, choices=PaymentMethod.choices, null=True, blank=True
    )
    amount_paid = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    void_reason = models.CharField(max_length=255, null=True, blank=True)
    created_by = models.ForeignKey(
        "accounts.Staff", on_delete=models.PROTECT, related_name="bills_created"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(status__in=["UNPAID", "PAID", "VOID"]), name="bill_status_valid"
            ),
            models.CheckConstraint(
                condition=models.Q(payment_method__isnull=True)
                | models.Q(payment_method__in=["CASH", "CARD", "EWALLET"]),
                name="bill_payment_method_valid",
            ),
            models.CheckConstraint(condition=models.Q(discount__gte=0), name="bill_discount_non_negative"),
            models.CheckConstraint(
                condition=models.Q(amount_paid__isnull=True) | models.Q(amount_paid__gte=0),
                name="bill_amount_paid_non_negative",
            ),
        ]

    def __str__(self):
        return self.bill_no

    # Totals are calculated from the items, not stored.
    @property
    def subtotal(self):
        return sum((item.line_total for item in self.items.all()), Decimal("0"))

    @property
    def tax_amount(self):
        return ((self.subtotal - self.discount) * self.tax_rate / 100).quantize(Decimal("0.01"))

    @property
    def total(self):
        return self.subtotal - self.discount + self.tax_amount

    @property
    def change_due(self):
        if self.payment_method == self.PaymentMethod.CASH and self.amount_paid is not None:
            return self.amount_paid - self.total
        return None

    def clean(self):
        # guide.md: amount_paid ≥ total for cash
        if (
            self.pk
            and self.payment_method == self.PaymentMethod.CASH
            and self.amount_paid is not None
            and self.amount_paid < self.total
        ):
            raise ValidationError({"amount_paid": "Cash paid must be at least the bill total."})


class BillItem(models.Model):
    class ItemType(models.TextChoices):
        CONSULTATION = "CONSULTATION", "Consultation"
        MEDICINE = "MEDICINE", "Medicine"

    bill_item_id = models.BigAutoField(primary_key=True)
    bill = models.ForeignKey(Bill, on_delete=models.CASCADE, related_name="items")
    item_type = models.CharField(max_length=12, choices=ItemType.choices)
    medicine = models.ForeignKey(
        "pharmacy.Medicine",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="bill_items",
    )
    description = models.CharField(max_length=150)
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=8, decimal_places=2)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(item_type__in=["CONSULTATION", "MEDICINE"]),
                name="bill_item_type_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(item_type="CONSULTATION") | models.Q(medicine__isnull=False),
                name="bill_item_medicine_required",
            ),
            models.CheckConstraint(condition=models.Q(quantity__gt=0), name="bill_item_quantity_positive"),
            models.CheckConstraint(condition=models.Q(unit_price__gte=0), name="bill_item_price_non_negative"),
        ]

    def __str__(self):
        return f"{self.description} × {self.quantity}"

    @property
    def line_total(self):
        return self.quantity * self.unit_price
