from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.utils import timezone

IC_REGEX = r"^\d{6}-\d{2}-\d{4}$"  # ######-##-####
PHONE_REGEX = r"^01\d-\d{7,8}$"  # 01X-XXXXXXX (011 numbers have 8 digits)


def validate_not_future(value):
    if value > timezone.localdate():
        raise ValidationError("Date of birth cannot be in the future.")


class Patient(models.Model):
    class Gender(models.TextChoices):
        MALE = "M", "Male"
        FEMALE = "F", "Female"

    patient_id = models.BigAutoField(primary_key=True)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="patient",
    )
    ic_no = models.CharField(
        "IC no.",
        max_length=14,
        unique=True,
        validators=[RegexValidator(IC_REGEX, "Format: ######-##-####")],
    )
    full_name = models.CharField(max_length=100)
    gender = models.CharField(max_length=1, choices=Gender.choices)
    date_of_birth = models.DateField(validators=[validate_not_future])
    phone = models.CharField(
        max_length=15, validators=[RegexValidator(PHONE_REGEX, "Format: 01X-XXXXXXX")]
    )
    email = models.EmailField(null=True, blank=True)
    address = models.CharField(max_length=255, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["full_name"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(ic_no__regex=IC_REGEX), name="patient_ic_format"
            ),
            models.CheckConstraint(
                condition=models.Q(phone__regex=PHONE_REGEX), name="patient_phone_format"
            ),
            models.CheckConstraint(
                condition=models.Q(gender__in=["M", "F"]), name="patient_gender_valid"
            ),
        ]

    def __str__(self):
        return f"{self.full_name} ({self.ic_no})"
