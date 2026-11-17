"""Tests for the Patient module.

Run without touching Supabase:
    python manage.py test patients --settings=clinicmq.settings_test
"""

import datetime as dt

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase

from patients import services as ps
from patients.models import Patient
from queueing.models import QueueTicket

User = get_user_model()


class PatientTestCase(TestCase):
    def setUp(self):
        self.nurse = User.objects.create_user(username="nurse", email="nurse@x.my", password="x", role="NURSE")
        self.doctor = User.objects.create_user(username="doc", email="doc@x.my", password="x", role="DOCTOR")
        self.admin = User.objects.create_user(username="admin", email="admin@x.my", password="x", role="ADMIN")

    def make_patient(self, n=1, online=False, **extra):
        user = None
        if online:
            user = User.objects.create_user(username=f"p{n}@x.my", email=f"p{n}@x.my",
                                            password="old-Pass-123", role="PATIENT")
        data = dict(user=user, ic_no=f"9001{n:02d}-14-56{n:02d}", full_name=f"PATIENT {n}", gender="F",
                    date_of_birth=dt.date(1990, 1, n), phone="012-3456789",
                    email=user.email if user else None)
        data.update(extra)
        return Patient.objects.create(**data)

    def add_ticket(self, patient, status="COMPLETED", day=dt.date(2026, 11, 4), no=1):
        return QueueTicket.objects.create(queue_date=day, queue_no=no, position=no, patient=patient,
                                          session="MORNING", source="WALKIN", status=status)


class ListAndVisitTests(PatientTestCase):
    def test_only_staff_can_list(self):
        self.make_patient(1)
        self.assertEqual(ps.list_patients(viewed_by=self.doctor).count(), 1)
        patient_user = User.objects.create_user(username="pp", email="pp@x.my", password="x", role="PATIENT")
        with self.assertRaises(PermissionDenied):
            ps.list_patients(viewed_by=patient_user)

    def test_last_visit_is_latest_completed_ticket(self):
        p = self.make_patient(1)
        self.add_ticket(p, "COMPLETED", dt.date(2026, 11, 1), 1)
        self.add_ticket(p, "COMPLETED", dt.date(2026, 11, 3), 1)
        self.add_ticket(p, "CANCELLED", dt.date(2026, 11, 5), 1)
        self.assertEqual(ps.last_visit_dates([p.pk]), {p.pk: dt.date(2026, 11, 3)})


class DeleteTests(PatientTestCase):
    def test_admin_deletes_patient_and_their_login(self):
        p = self.make_patient(1, online=True)
        user_id = p.user_id
        ps.delete_patient(deleted_by=self.admin, patient_id=p.pk)
        self.assertFalse(Patient.objects.exists())
        self.assertFalse(User.objects.filter(pk=user_id).exists())

    def test_blocked_once_patient_has_a_ticket(self):
        p = self.make_patient(1)
        self.add_ticket(p, "CANCELLED")
        with self.assertRaisesMessage(ValidationError, "has visits and cannot be deleted"):
            ps.delete_patient(deleted_by=self.admin, patient_id=p.pk)

    def test_only_admin_can_delete(self):
        p = self.make_patient(1)
        with self.assertRaises(PermissionDenied):
            ps.delete_patient(deleted_by=self.nurse, patient_id=p.pk)


class EmailChangeTests(PatientTestCase):
    def setUp(self):
        super().setUp()
        self.p = self.make_patient(1, online=True)
        self.user = self.p.user

    def start(self, email="new@x.my", password="old-Pass-123"):
        return ps.start_email_change(user=self.user, new_email=email, password=password)

    def code_from_email(self):
        return [w for w in mail.outbox[-1].body.split() if w.isdigit() and len(w) == 6][0]

    def test_code_sent_to_new_email_then_both_emails_change(self):
        pending = self.start("New@X.my")
        self.assertEqual(mail.outbox[-1].to, ["new@x.my"])
        ps.confirm_email_change(user=self.user, pending=pending, code=self.code_from_email())
        self.user.refresh_from_db(), self.p.refresh_from_db()
        self.assertEqual((self.user.email, self.user.username, self.p.email), ("new@x.my",) * 3)

    def test_needs_correct_password_and_unused_email(self):
        with self.assertRaises(ValidationError) as e:
            self.start(password="wrong")
        self.assertIn("password", e.exception.message_dict)
        with self.assertRaises(ValidationError) as e:
            self.start(email="nurse@x.my")
        self.assertIn("already exists", e.exception.message_dict["new_email"][0])

    def test_wrong_code_counts_tries_then_locks(self):
        pending = self.start()
        for left in (4, 3, 2, 1):
            with self.assertRaisesMessage(ValidationError, f"{left} tr"):
                ps.confirm_email_change(user=self.user, pending=pending, code="000000x")
        with self.assertRaisesMessage(ValidationError, "Too many wrong codes"):
            ps.confirm_email_change(user=self.user, pending=pending, code="000000x")
        with self.assertRaisesMessage(ValidationError, "Too many wrong codes"):
            ps.confirm_email_change(user=self.user, pending=pending, code=self.code_from_email())
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "p1@x.my")

    def test_code_expires(self):
        pending = self.start()
        pending["expires"] -= 11 * 60
        with self.assertRaisesMessage(ValidationError, "expired"):
            ps.confirm_email_change(user=self.user, pending=pending, code=self.code_from_email())
