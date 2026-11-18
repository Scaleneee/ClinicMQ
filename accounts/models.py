from django.contrib.auth.models import AbstractUser, UserManager
from django.core.exceptions import ObjectDoesNotExist
from django.db import models


class Session(models.TextChoices):
    """Clinic session. Shared by Shift and QueueTicket."""

    MORNING = "MORNING", "Morning"
    NIGHT = "NIGHT", "Night"


class ClinicUserManager(UserManager):
    def create_superuser(self, username, email=None, password=None, **extra_fields):
        # `manage.py createsuperuser` doesn't ask for a role, so make it ADMIN.
        extra_fields.setdefault("role", "ADMIN")
        return super().create_superuser(username, email, password, **extra_fields)


class User(AbstractUser):
    """Login account with a clinic role. See guide.md → Database → User."""

    objects = ClinicUserManager()

    class Role(models.TextChoices):
        PATIENT = "PATIENT", "Patient"
        NURSE = "NURSE", "Nurse"
        DOCTOR = "DOCTOR", "Doctor"
        ADMIN = "ADMIN", "Admin"

    # Names live on Patient.full_name / Staff.full_name (one field, as on the IC),
    # so drop Django's built-in first/last name columns.
    first_name = None
    last_name = None

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

    def get_full_name(self):
        """Full name from the linked Patient or Staff record, else the username."""
        for related in ("patient", "staff"):
            try:
                return getattr(self, related).full_name
            except ObjectDoesNotExist:
                continue
        return self.username

    def get_short_name(self):
        return self.get_full_name()


class Staff(models.Model):
    """Profile of a doctor, nurse or admin.

    The role and the active flag live on the linked User only (user.role, user.is_active),
    so they can never disagree. A deactivated staff member's user can't log in.
    """

    ROLES = (User.Role.DOCTOR, User.Role.NURSE, User.Role.ADMIN)

    staff_id = models.BigAutoField(primary_key=True)
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="staff")
    full_name = models.CharField(max_length=100)
    phone = models.CharField(max_length=15)
    specialty = models.CharField(max_length=100, null=True, blank=True)

    class Meta:
        verbose_name_plural = "staff"

    def __str__(self):
        return f"{self.full_name} ({self.user.role})"


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
