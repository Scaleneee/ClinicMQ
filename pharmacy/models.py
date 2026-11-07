from django.db import models


class Medicine(models.Model):
    medicine_id = models.BigAutoField(primary_key=True)
    name = models.CharField(max_length=100, unique=True)
    category = models.CharField(max_length=50)
    unit = models.CharField(max_length=20)
    unit_price = models.DecimalField(max_digits=8, decimal_places=2)
    quantity = models.PositiveIntegerField()
    reorder_level = models.PositiveIntegerField(default=10)
    expiry_date = models.DateField()
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(unit_price__gt=0), name="medicine_price_positive"
            ),
        ]

    def __str__(self):
        return self.name

    @property
    def is_low_stock(self):
        return self.quantity <= self.reorder_level


class PrescriptionItem(models.Model):
    """One medicine in a consultation's prescription. PK is (consultation, medicine)."""

    pk = models.CompositePrimaryKey("consultation", "medicine")
    consultation = models.ForeignKey(
        "consultation.Consultation", on_delete=models.CASCADE, related_name="prescription_items"
    )
    medicine = models.ForeignKey(
        Medicine, on_delete=models.PROTECT, related_name="prescription_items"
    )
    dosage = models.CharField(max_length=100)
    quantity = models.PositiveIntegerField()
    dispensed = models.BooleanField(default=False)
    dispensed_at = models.DateTimeField(null=True, blank=True)
    dispensed_by = models.ForeignKey(
        "accounts.Staff",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="dispensed_items",
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0), name="prescription_quantity_positive"
            ),
        ]

    def __str__(self):
        return f"{self.medicine.name} × {self.quantity}"
