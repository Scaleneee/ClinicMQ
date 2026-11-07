from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """Custom user with a clinic role. See guide.md → Database → User."""

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
