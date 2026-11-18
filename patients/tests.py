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
        data = dict(user=user, ic_no=f"9001{n:02d}-14-56{n:02d}", full_name=f"PATIENT {n}",
                    gender="M" if n % 2 else "F",  # last IC digit: odd = male, even = female
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


# ---------------------------------------------------------------------------
# Screens
# ---------------------------------------------------------------------------
from decimal import Decimal  # noqa: E402

from django.urls import reverse  # noqa: E402

from accounts.models import Staff  # noqa: E402
from consultation.models import Consultation, MedicalCertificate  # noqa: E402
from pharmacy.models import Medicine, PrescriptionItem  # noqa: E402


class ListAndDetailScreenTests(PatientTestCase):
    def test_list_search_and_pagination(self):
        for n in range(1, 26):
            self.make_patient(n)
        self.client.force_login(self.nurse)
        page = self.client.get(reverse("patients:list"))
        self.assertContains(page, "Page 1 of 2")
        page = self.client.get(reverse("patients:list") + "?q=900105")
        self.assertContains(page, "Patient 5")
        self.assertContains(page, "1 result for")
        page = self.client.get(reverse("patients:list") + "?q=zzz")
        self.assertContains(page, "No patient matches")

    def test_patients_cannot_open_staff_pages(self):
        p = self.make_patient(1, online=True)
        self.client.force_login(p.user)
        self.assertEqual(self.client.get(reverse("patients:list")).status_code, 403)
        self.assertEqual(self.client.get(reverse("patients:detail", args=[p.pk])).status_code, 403)

    def test_detail_shows_visit_timeline(self):
        p = self.make_patient(1)
        doc = Staff.objects.create(user=self.doctor, full_name="Aisyah Rahman", phone="012-0000000")
        ticket = self.add_ticket(p, "COMPLETED")
        c = Consultation.objects.create(ticket=ticket, doctor=doc, symptoms="Fever", diagnosis="Viral fever",
                                        consult_fee=Decimal("30"))
        med = Medicine.objects.create(name="Paracetamol 500mg", category="Analgesic", unit="tablet",
                                      unit_price=Decimal("0.50"), quantity=100, expiry_date=dt.date(2027, 1, 1))
        PrescriptionItem.objects.create(consultation=c, medicine=med, dosage="2 tabs 3x a day", quantity=20)
        MedicalCertificate.objects.create(mc_no="MC-1", consultation=c, start_date=dt.date(2026, 11, 4),
                                          days=2, reason="Fever")
        self.client.force_login(self.doctor)
        page = self.client.get(reverse("patients:detail", args=[p.pk]))
        for text in ("Viral fever", "Dr. Aisyah Rahman", "Paracetamol 500mg", "· 2 tabs 3x a day", "MC 2 days"):
            self.assertContains(page, text)
        self.assertNotContains(page, "Issue number")  # doctors don't issue numbers


class CreateEditDeleteScreenTests(PatientTestCase):
    VALID = {"ic_no": "900101145678", "full_name": "siti nurhaliza", "gender": "F",
             "date_of_birth": "1990-01-01", "phone": "0123456789", "email": "", "address": "Setapak"}

    def test_nurse_adds_patient(self):
        self.client.force_login(self.nurse)
        page = self.client.post(reverse("patients:create"), self.VALID, follow=True)
        p = Patient.objects.get()
        self.assertEqual((p.ic_no, p.full_name, p.phone), ("900101-14-5678", "SITI NURHALIZA", "012-3456789"))
        self.assertContains(page, "Siti Nurhaliza was registered.")

    def test_add_shows_service_errors(self):
        self.make_patient(1)  # IC 900101-14-5601
        self.client.force_login(self.nurse)
        page = self.client.post(reverse("patients:create"), {**self.VALID, "ic_no": "900101-14-5601"})
        self.assertContains(page, "already registered")
        page = self.client.post(reverse("patients:create"), {**self.VALID, "date_of_birth": "1990-01-02",
                                                             "gender": "M"})
        self.assertContains(page, "does not match IC")

    def test_add_from_walk_in_goes_back_with_patient_selected(self):
        self.client.force_login(self.nurse)
        page = self.client.post(reverse("patients:create"), {**self.VALID, "next": "walk_in"})
        self.assertRedirects(page, reverse("queueing:walk_in") + f"?patient={Patient.objects.get().pk}",
                             fetch_redirect_response=False)

    def test_edit_keeps_linked_login_email(self):
        p = self.make_patient(1, online=True)
        self.client.force_login(self.nurse)
        data = {"ic_no": p.ic_no, "full_name": "Patient One", "gender": p.gender, "date_of_birth": "1990-01-01",
                "phone": "019-8887777", "email": "hacker@x.my", "address": ""}
        page = self.client.post(reverse("patients:edit", args=[p.pk]), data, follow=True)
        self.assertContains(page, "Patient details saved.")
        p.refresh_from_db()
        self.assertEqual((p.full_name, p.phone, p.email), ("PATIENT ONE", "019-8887777", "p1@x.my"))

    def test_doctor_cannot_add_or_edit(self):
        p = self.make_patient(1)
        self.client.force_login(self.doctor)
        self.assertEqual(self.client.get(reverse("patients:create")).status_code, 403)
        self.assertEqual(self.client.get(reverse("patients:edit", args=[p.pk])).status_code, 403)

    def test_admin_delete_and_blocked_state(self):
        a, b = self.make_patient(1), self.make_patient(2)
        self.add_ticket(b)
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse("patients:delete", args=[b.pk])), "has visits and cannot be deleted")
        page = self.client.post(reverse("patients:delete", args=[a.pk]), follow=True)
        self.assertContains(page, "Patient 1 was deleted.")
        self.assertEqual(list(Patient.objects.values_list("pk", flat=True)), [b.pk])
        self.client.force_login(self.nurse)
        self.assertEqual(self.client.get(reverse("patients:delete", args=[b.pk])).status_code, 403)


class MyProfileScreenTests(PatientTestCase):
    def setUp(self):
        super().setUp()
        self.p = self.make_patient(1, online=True)
        self.client.force_login(self.p.user)

    def test_edit_phone_and_address_only(self):
        page = self.client.get(reverse("patients:my_profile"))
        self.assertContains(page, self.p.ic_no)
        self.assertNotContains(page, 'name="full_name"')  # read-only
        page = self.client.post(reverse("patients:my_profile"), {"phone": "0198887777", "address": "Setapak"},
                                follow=True)
        self.assertContains(page, "Your details were saved.")
        self.p.refresh_from_db()
        self.assertEqual((self.p.phone, self.p.address), ("019-8887777", "Setapak"))

    def test_email_change_with_password_and_code(self):
        page = self.client.post(reverse("patients:change_email"),
                                {"new_email": "fresh@x.my", "password": "wrong"})
        self.assertContains(page, "Incorrect password.")

        page = self.client.post(reverse("patients:change_email"),
                                {"new_email": "fresh@x.my", "password": "old-Pass-123"}, follow=True)
        self.assertRedirects(page, reverse("patients:verify_email"))
        self.assertContains(page, "We sent a 6-digit code to fresh@x.my")
        code = [w for w in mail.outbox[-1].body.split() if w.isdigit() and len(w) == 6][0]

        wrong = "000000" if code != "000000" else "111111"
        page = self.client.post(reverse("patients:verify_email"), {"code": wrong})
        self.assertContains(page, "Incorrect code. 4 tries left.")

        page = self.client.post(reverse("patients:verify_email"), {"code": code}, follow=True)
        self.assertContains(page, "Your email is now fresh@x.my")
        self.p.user.refresh_from_db()
        self.assertEqual(self.p.user.email, "fresh@x.my")
        # log in with the new email
        self.client.logout()
        login = self.client.post(reverse("login"), {"username": "fresh@x.my", "password": "old-Pass-123"})
        self.assertEqual(login.status_code, 302)

    def test_verify_without_request_goes_to_step_one(self):
        self.assertRedirects(self.client.get(reverse("patients:verify_email")), reverse("patients:change_email"))


class MyVisitsScreenTests(PatientTestCase):
    def test_patient_sees_only_own_visits(self):
        mine, other = self.make_patient(1, online=True), self.make_patient(2, online=True)
        doc = Staff.objects.create(user=self.doctor, full_name="Aisyah Rahman", phone="012-0000000")
        for p, diagnosis, no in ((mine, "Viral fever", 1), (other, "Sprained ankle", 2)):
            Consultation.objects.create(ticket=self.add_ticket(p, no=no), doctor=doc, symptoms="-",
                                        diagnosis=diagnosis, consult_fee=Decimal("30"))
        self.client.force_login(mine.user)
        page = self.client.get(reverse("patients:my_visits"))
        self.assertContains(page, "Viral fever")
        self.assertNotContains(page, "Sprained ankle")
        # navbar and home page now link here
        self.assertContains(self.client.get(reverse("dashboard")), reverse("patients:my_visits"))

    def test_no_visits_empty_state(self):
        p = self.make_patient(1, online=True)
        self.client.force_login(p.user)
        self.assertContains(self.client.get(reverse("patients:my_visits")), "No visits yet.")
