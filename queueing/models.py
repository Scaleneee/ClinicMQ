import datetime
import uuid

from django.db import models

from accounts.models import Session


class ClinicSetting(models.Model):
    """Single-row table of clinic-wide settings. Use ClinicSetting.load()."""

    clinic_name = models.CharField(max_length=100, default="ClinicMQ")
    address = models.CharField(max_length=255, blank=True, default="")
    phone = models.CharField(max_length=15, blank=True, default="")
    morning_start = models.TimeField(default=datetime.time(9, 0))
    morning_end = models.TimeField(default=datetime.time(13, 0))
    night_start = models.TimeField(default=datetime.time(18, 0))
    night_end = models.TimeField(default=datetime.time(22, 0))
    online_cutoff_min = models.PositiveSmallIntegerField(default=30)
    grace_count = models.PositiveSmallIntegerField(default=3)
    miss_timeout_min = models.PositiveSmallIntegerField(default=3)
    default_consult_min = models.PositiveSmallIntegerField(default=10)
    near_alert_threshold = models.PositiveSmallIntegerField(default=3)

    class Meta:
        verbose_name = "clinic setting"
        verbose_name_plural = "clinic setting"

    def __str__(self):
        return self.clinic_name

    def save(self, *args, **kwargs):
        self.pk = 1  # always the same row
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class QueueTicketQuerySet(models.QuerySet):
    def today(self):
        from django.utils import timezone

        return self.filter(queue_date=timezone.localdate())

    def active(self):
        return self.filter(
            status__in=[
                QueueTicket.Status.WAITING,
                QueueTicket.Status.CHECKED_IN,
                QueueTicket.Status.SKIPPED,
                QueueTicket.Status.CALLED,
                QueueTicket.Status.IN_CONSULTATION,
            ]
        )


class QueueTicket(models.Model):
    class Source(models.TextChoices):
        ONLINE = "ONLINE", "Online"
        WALKIN = "WALKIN", "Walk-in"

    class Status(models.TextChoices):
        WAITING = "WAITING", "Waiting"
        CHECKED_IN = "CHECKED_IN", "Checked in"
        SKIPPED = "SKIPPED", "Skipped"
        CALLED = "CALLED", "Called"
        IN_CONSULTATION = "IN_CONSULTATION", "In consultation"
        COMPLETED = "COMPLETED", "Completed"
        MISSED = "MISSED", "Missed"
        CANCELLED = "CANCELLED", "Cancelled"
        EXPIRED = "EXPIRED", "Expired"

    ticket_id = models.BigAutoField(primary_key=True)
    queue_date = models.DateField()
    queue_no = models.PositiveIntegerField()
    position = models.DecimalField(max_digits=8, decimal_places=2)
    patient = models.ForeignKey(
        "patients.Patient", on_delete=models.PROTECT, related_name="queue_tickets"
    )
    doctor = models.ForeignKey(
        "accounts.Staff",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="queue_tickets",
    )
    session = models.CharField(max_length=7, choices=Session.choices)
    source = models.CharField(max_length=8, choices=Source.choices)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.WAITING)
    rejoined = models.BooleanField(default=False)
    miss_count = models.PositiveSmallIntegerField(default=0)
    last_ahead = models.IntegerField(null=True, blank=True)
    near_alert_sent = models.BooleanField(default=False)
    called_alert_sent = models.BooleanField(default=False)
    issued_at = models.DateTimeField(auto_now_add=True)
    checked_in_at = models.DateTimeField(null=True, blank=True)
    called_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    public_token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)

    objects = QueueTicketQuerySet.as_manager()

    class Meta:
        ordering = ["queue_date", "position"]
        constraints = [
            models.UniqueConstraint(fields=["queue_date", "queue_no"], name="ticket_unique_no_per_day"),
            models.CheckConstraint(
                condition=models.Q(session__in=["MORNING", "NIGHT"]), name="ticket_session_valid"
            ),
            models.CheckConstraint(
                condition=models.Q(source__in=["ONLINE", "WALKIN"]), name="ticket_source_valid"
            ),
            models.CheckConstraint(
                condition=models.Q(
                    status__in=[
                        "WAITING", "CHECKED_IN", "SKIPPED", "CALLED", "IN_CONSULTATION",
                        "COMPLETED", "MISSED", "CANCELLED", "EXPIRED",
                    ]
                ),
                name="ticket_status_valid",
            ),
            models.CheckConstraint(condition=models.Q(miss_count__lte=2), name="ticket_miss_count_max_2"),
        ]

    def __str__(self):
        return f"#{self.queue_no} · {self.queue_date} · {self.patient.full_name}"
