from django.contrib.auth.models import AbstractUser
from django.db import models


class Session(models.TextChoices):
    """Clinic session. Shared by Shift and QueueTicket."""

    MORNING = "MORNING", "Morning"
    NIGHT = "NIGHT", "Night"


class User(AbstractUser):
    """Login account with a clinic role. See guide.md → Database → User."""

    class Role(models.TextChoices):
        PATIENT = "PATIENT", "Patient"
        NURSE = "NURSE", "Nurse"
        DOCTOR = "DOCTOR", "Doctor"
        ADMIN = "ADMIN", "Admin"

    email = models.EmailField(unique=True)
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.PATIENT)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(role__in=["PATIENT", "NURSE", "DOCTOR", "ADMIN"]),
                name="user_role_valid",
            ),
        ]

    def __str__(self):
        return f"{self.username} ({self.role})"


class Staff(models.Model):
    class Role(models.TextChoices):
        DOCTOR = "DOCTOR", "Doctor"
        NURSE = "NURSE", "Nurse"
        ADMIN = "ADMIN", "Admin"

    staff_id = models.BigAutoField(primary_key=True)
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="staff")
    full_name = models.CharField(max_length=100)
    role = models.CharField(max_length=10, choices=Role.choices)
    phone = models.CharField(max_length=15)
    specialty = models.CharField(max_length=100, null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name_plural = "staff"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(role__in=["DOCTOR", "NURSE", "ADMIN"]),
                name="staff_role_valid",
            ),
        ]

    def __str__(self):
        return f"{self.full_name} ({self.role})"


class Shift(models.Model):
    shift_id = models.BigAutoField(primary_key=True)
    staff = models.ForeignKey(Staff, on_delete=models.CASCADE, related_name="shifts")
    shift_date = models.DateField()
    session = models.CharField(max_length=7, choices=Session.choices)

    class Meta:
        ordering = ["shift_date", "session"]
        constraints = [
            models.UniqueConstraint(
                fields=["staff", "shift_date", "session"], name="shift_unique_staff_date_session"
            ),
            models.CheckConstraint(
                condition=models.Q(session__in=["MORNING", "NIGHT"]), name="shift_session_valid"
            ),
        ]

    def __str__(self):
        return f"{self.staff.full_name} · {self.shift_date} {self.session}"
