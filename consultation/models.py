from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class Consultation(models.Model):
    consultation_id = models.BigAutoField(primary_key=True)
    ticket = models.OneToOneField(
        "queueing.QueueTicket", on_delete=models.PROTECT, related_name="consultation"
    )
    doctor = models.ForeignKey(
        "accounts.Staff", on_delete=models.PROTECT, related_name="consultations"
    )
    symptoms = models.TextField()
    diagnosis = models.CharField(max_length=255)
    notes = models.TextField(null=True, blank=True)
    consult_fee = models.DecimalField(max_digits=8, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(consult_fee__gt=0), name="consultation_fee_positive"
            ),
        ]

    def __str__(self):
        return f"Consultation {self.consultation_id} · {self.ticket.patient.full_name}"


class MedicalCertificate(models.Model):
    mc_id = models.BigAutoField(primary_key=True)
    mc_no = models.CharField("MC no.", max_length=20, unique=True)
    consultation = models.OneToOneField(
        Consultation, on_delete=models.PROTECT, related_name="medical_certificate"
    )
    start_date = models.DateField()
    days = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(7)]
    )
    reason = models.CharField(max_length=255)
    issued_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(days__gte=1, days__lte=7), name="mc_days_1_to_7"
            ),
        ]

    def __str__(self):
        return self.mc_no
