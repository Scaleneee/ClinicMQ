"""Tests for the Consultation Record module.

Run without touching Supabase:
    python manage.py test consultation --settings=clinicmq.settings_test
"""

import datetime as dt
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.utils import timezone

from accounts.models import Shift, Staff
from billing.models import Bill
from consultation import services as cs
from consultation.models import Consultation, MedicalCertificate
from patients.models import Patient
from pharmacy.models import Medicine, PrescriptionItem
from queueing import services as q

User = get_user_model()
TODAY = dt.date(2026, 11, 4)


class ConsultationTestCase(TestCase):
    def setUp(self):
        clock = mock.patch("django.utils.timezone.now",
                           return_value=timezone.make_aware(dt.datetime.combine(TODAY, dt.time(10))))
        clock.start()
        self.addCleanup(clock.stop)

        self.doc = self.staff("Aisyah Rahman", "DOCTOR")
        self.doc2 = self.staff("Tan Wei Ming", "DOCTOR")
        self.nurse = self.staff("Farah Lim", "NURSE")
        self.admin = self.staff("Kumar", "ADMIN")
        Shift.objects.create(staff=self.doc, shift_date=TODAY, session="MORNING")
        self.patient = Patient.objects.create(ic_no="900101-14-5678", full_name="SITI NURHALIZA", gender="F",
                                              date_of_birth=dt.date(1990, 1, 1), phone="012-3456789")
        self.para = Medicine.objects.create(name="Paracetamol 500mg", category="Analgesic", unit="tablets",
                                            unit_price=Decimal("0.50"), quantity=100,
                                            expiry_date=TODAY + dt.timedelta(days=365))
        self.syrup = Medicine.objects.create(name="Cough syrup 100ml", category="Cough", unit="bottles",
                                             unit_price=Decimal("8.00"), quantity=2,
                                             expiry_date=TODAY + dt.timedelta(days=365))
        self.empty = Medicine.objects.create(name="Amoxicillin 250mg", category="Antibiotic", unit="capsules",
                                             unit_price=Decimal("1.00"), quantity=0,
                                             expiry_date=TODAY + dt.timedelta(days=365))
        self.ticket = self.with_doctor()

    def staff(self, name, role):
        email = f"{name.split()[0].lower()}@clinic.my"
        user = User.objects.create_user(username=email, email=email, password="x", role=role)
        return Staff.objects.create(user=user, full_name=name, role=role, phone="012-0000000")

    def with_doctor(self):
        t = q.issue_ticket(issued_by=self.nurse.user, patient=self.patient, source="WALKIN")
        q.call_next(called_by=self.nurse.user)
        return q.start_consultation(started_by=self.doc.user, ticket_id=t.pk)

    def create(self, **kw):
        data = dict(doctor_user=self.doc.user, ticket_id=self.ticket.pk, symptoms="Fever and cough, 2 days",
                    diagnosis="Viral fever", consult_fee="30", notes="Rest well",
                    items=[{"medicine": self.para.pk, "dosage": "2 tabs, 3 times a day", "quantity": 20}])
        data.update(kw)
        return cs.create_consultation(**data)


class CreateTests(ConsultationTestCase):
    def test_create_with_prescription_and_mc(self):
        c, warnings = self.create(mc={"start_date": TODAY, "days": 2, "reason": "Viral fever"})
        self.assertEqual((c.doctor, c.diagnosis, c.consult_fee), (self.doc, "Viral fever", Decimal("30.00")))
        self.assertEqual([(i.medicine.name, i.quantity) for i in c.prescription_items.all()],
                         [("Paracetamol 500mg", 20)])
        mc = c.medical_certificate
        self.assertEqual((mc.mc_no, mc.days, cs.mc_end_date(mc)), ("MC-20261104-001", 2, dt.date(2026, 11, 5)))
        self.assertEqual(warnings, [])
        self.assertEqual(cs.consultation_total(c), Decimal("40.00"))

    def test_validation(self):
        with self.assertRaises(ValidationError) as e:
            self.create(symptoms="", diagnosis=" ", consult_fee="0",
                        items=[{"medicine": self.empty.pk, "dosage": "", "quantity": 0}],
                        mc={"start_date": TODAY, "days": 8, "reason": ""})
        d = e.exception.message_dict
        self.assertEqual(set(d), {"symptoms", "diagnosis", "consult_fee", "items", "mc_days", "mc_reason"})
        self.assertIn("Amoxicillin 250mg is out of stock and can't be prescribed.", d["items"])

    def test_same_medicine_twice_rejected(self):
        row = {"medicine": self.para.pk, "dosage": "1 tab", "quantity": 5}
        with self.assertRaisesMessage(ValidationError, "already in the prescription"):
            self.create(items=[row, row])

    def test_stock_warning_but_saved(self):
        c, warnings = self.create(items=[{"medicine": self.syrup.pk, "dosage": "10ml 3x", "quantity": 3}])
        self.assertEqual(c.prescription_items.count(), 1)
        self.assertIn("Only 2 bottles of Cough syrup 100ml in stock", warnings[0])

    def test_one_per_ticket_and_only_doctors(self):
        self.create()
        with self.assertRaisesMessage(ValidationError, "already has a consultation"):
            self.create()
        with self.assertRaises(PermissionDenied):
            self.create(doctor_user=self.nurse.user)

    def test_ticket_must_be_with_doctor_or_completed(self):
        p2 = Patient.objects.create(ic_no="880808-14-6789", full_name="RAJ", gender="M",
                                    date_of_birth=dt.date(1988, 8, 8), phone="012-1112222")
        waiting = q.issue_ticket(issued_by=self.nurse.user, patient=p2, source="WALKIN")
        with self.assertRaisesMessage(ValidationError, "with the doctor or after the visit"):
            self.create(ticket_id=waiting.pk)

    def test_mc_numbers_go_up(self):
        self.create(mc={"start_date": TODAY, "days": 1, "reason": "Fever"})
        q.complete_ticket(completed_by=self.doc.user, ticket_id=self.ticket.pk)
        p2 = Patient.objects.create(ic_no="880808-14-6789", full_name="RAJ", gender="M",
                                    date_of_birth=dt.date(1988, 8, 8), phone="012-1112222")
        self.patient = p2
        t2 = self.with_doctor()
        c2, _ = self.create(ticket_id=t2.pk, mc={"start_date": TODAY, "days": 3, "reason": "Flu"})
        self.assertEqual(c2.medical_certificate.mc_no, "MC-20261104-002")


class UpdateDeleteTests(ConsultationTestCase):
    def update(self, c, **kw):
        data = dict(doctor_user=self.doc.user, consultation_id=c.pk, symptoms=c.symptoms, diagnosis=c.diagnosis,
                    consult_fee=c.consult_fee, notes=c.notes,
                    items=[{"medicine": i.medicine_id, "dosage": i.dosage, "quantity": i.quantity}
                           for i in c.prescription_items.all()])
        data.update(kw)
        return cs.update_consultation(**data)

    def test_edit_diagnosis_items_and_mc(self):
        c, _ = self.create()
        c, _ = self.update(c, diagnosis="Influenza",
                           items=[{"medicine": self.syrup.pk, "dosage": "10ml 3x", "quantity": 1}],
                           mc={"start_date": TODAY, "days": 2, "reason": "Influenza"})
        self.assertEqual(c.diagnosis, "Influenza")
        self.assertEqual([i.medicine_id for i in c.prescription_items.all()], [self.syrup.pk])
        self.assertTrue(MedicalCertificate.objects.filter(consultation=c).exists())
        c, _ = self.update(c, mc=None)  # untick "Issue MC"
        self.assertFalse(MedicalCertificate.objects.filter(consultation=c).exists())

    def test_only_the_author_edits(self):
        c, _ = self.create()
        with self.assertRaises(PermissionDenied):
            self.update(c, doctor_user=self.doc2.user, diagnosis="x")

    def test_billed_locks_fee_and_medicines(self):
        c, _ = self.create()
        Bill.objects.create(bill_no="B-1", consultation=c, created_by=self.nurse)
        c, _ = self.update(c, diagnosis="Influenza", consult_fee="99", items=[])
        self.assertEqual((c.diagnosis, c.consult_fee, c.prescription_items.count()),
                         ("Influenza", Decimal("30.00"), 1))
        with self.assertRaisesMessage(ValidationError, "billed"):
            cs.delete_consultation(deleted_by=self.doc.user, consultation_id=c.pk)

    def test_dispensed_items_are_locked(self):
        c, _ = self.create()
        PrescriptionItem.objects.filter(consultation=c).update(dispensed=True)
        with self.assertRaisesMessage(ValidationError, "already dispensed and can't be removed"):
            self.update(c, items=[])
        with self.assertRaisesMessage(ValidationError, "already dispensed"):
            cs.delete_consultation(deleted_by=self.admin.user, consultation_id=c.pk)

    def test_delete_by_author_or_admin(self):
        c, _ = self.create(mc={"start_date": TODAY, "days": 1, "reason": "Fever"})
        with self.assertRaises(PermissionDenied):
            cs.delete_consultation(deleted_by=self.nurse.user, consultation_id=c.pk)
        cs.delete_consultation(deleted_by=self.doc.user, consultation_id=c.pk)
        self.assertFalse(Consultation.objects.exists())
        self.assertFalse(MedicalCertificate.objects.exists())

    def test_visits_without_notes(self):
        self.assertEqual(list(cs.visits_without_notes(doctor_user=self.doc.user)), [self.ticket])
        self.create()
        self.assertEqual(list(cs.visits_without_notes(doctor_user=self.doc.user)), [])


# ---------------------------------------------------------------------------
# Screens
# ---------------------------------------------------------------------------
from django.urls import reverse  # noqa: E402


class ListDetailScreenTests(ConsultationTestCase):
    def test_list_and_detail(self):
        c, _ = self.create(mc={"start_date": TODAY, "days": 2, "reason": "Viral fever"})
        self.client.force_login(self.nurse.user)
        page = self.client.get(reverse("consultation:list"))
        self.assertContains(page, "Viral fever")
        self.assertContains(page, "Siti Nurhaliza")
        self.assertContains(page, "2 days")
        page = self.client.get(reverse("consultation:list") + "?q=nothing")
        self.assertContains(page, "No consultation matches")

        page = self.client.get(reverse("consultation:detail", args=[c.pk]))
        for text in ("Fever and cough, 2 days", "Paracetamol 500mg", "RM 10.00", "Waiting",
                     "MC-20261104-001", "4 Nov – 5 Nov 2026", "RM 40.00", "Not billed yet"):
            self.assertContains(page, text)

    def test_doctor_sees_visits_needing_notes(self):
        self.client.force_login(self.doc.user)
        page = self.client.get(reverse("consultation:list"))
        self.assertContains(page, "Visits waiting for your notes today")
        self.assertContains(page, "001 · Siti Nurhaliza")

    def test_patients_cannot_view(self):
        u = User.objects.create_user(username="p@x.my", email="p@x.my", password="x", role="PATIENT")
        self.client.force_login(u)
        self.assertEqual(self.client.get(reverse("consultation:list")).status_code, 403)


class FormScreenTests(ConsultationTestCase):
    def post(self, url, **extra):
        data = {"symptoms": "Fever, cough", "diagnosis": "Viral fever", "notes": "", "consult_fee": "30.00",
                "medicine": [str(self.para.pk), ""], "dosage": ["2 tabs 3x a day", ""], "quantity": ["20", ""]}
        data.update(extra)
        return self.client.post(url, data, follow=True)

    def test_write_notes_from_console_and_back(self):
        self.client.force_login(self.doc.user)
        console = self.client.get(reverse("queueing:console"))
        url = reverse("consultation:create", args=[self.ticket.pk])
        self.assertContains(console, url + "?next=console")                  # "Write notes" now works
        form = self.client.get(url + "?next=console")
        self.assertContains(form, "Siti Nurhaliza")                          # patient strip
        self.assertContains(form, "Amoxicillin 250mg (out of stock)")       # disabled option
        page = self.post(url, next="console", issue_mc="on", mc_start_date="2026-11-04", mc_days="2",
                         mc_reason="Viral fever")
        self.assertRedirects(page, reverse("queueing:console"))
        self.assertContains(page, "Consultation saved.")
        self.assertContains(page, "Edit notes")
        c = Consultation.objects.get()
        self.assertEqual((c.prescription_items.count(), c.medical_certificate.days), (1, 2))

    def test_errors_and_stock_warning(self):
        self.client.force_login(self.doc.user)
        url = reverse("consultation:create", args=[self.ticket.pk])
        page = self.post(url, diagnosis="")
        self.assertContains(page, "Please fix the fields marked in red.")
        self.assertContains(page, "This field is required.")                # diagnosis
        page = self.post(url, issue_mc="on", mc_days="", mc_reason="")
        self.assertContains(page, "Enter the reason for the MC.")
        self.assertFalse(Consultation.objects.exists())
        page = self.post(url, medicine=[str(self.syrup.pk)], dosage=["10ml"], quantity=["5"])
        self.assertContains(page, "Only 2 bottles of Cough syrup 100ml in stock")
        self.assertEqual(Consultation.objects.count(), 1)

    def test_service_row_errors_shown(self):
        self.client.force_login(self.doc.user)
        url = reverse("consultation:create", args=[self.ticket.pk])
        page = self.post(url, medicine=[str(self.para.pk)], dosage=[""], quantity=["0"])
        self.assertContains(page, "Row 1: enter the dosage for Paracetamol 500mg.")
        self.assertContains(page, "Row 1: quantity for Paracetamol 500mg must be more than 0.")

    def test_edit_by_author_only_and_billed_locks(self):
        c, _ = self.create()
        self.client.force_login(self.doc2.user)
        page = self.client.get(reverse("consultation:edit", args=[c.pk]), follow=True)
        self.assertContains(page, "Only the doctor who wrote this consultation can edit it.")

        Bill.objects.create(bill_no="B-1", consultation=c, created_by=self.nurse)
        self.client.force_login(self.doc.user)
        page = self.client.get(reverse("consultation:edit", args=[c.pk]))
        self.assertContains(page, "locked, already billed")
        page = self.post(reverse("consultation:edit", args=[c.pk]), diagnosis="Influenza", consult_fee="99",
                         medicine=[str(self.para.pk)], dosage=["2 tabs 3x a day"], quantity=["20"])
        self.assertContains(page, "Consultation updated.")
        c.refresh_from_db()
        self.assertEqual((c.diagnosis, c.consult_fee), ("Influenza", Decimal("30.00")))

    def test_nurse_cannot_write(self):
        self.client.force_login(self.nurse.user)
        self.assertEqual(self.client.get(reverse("consultation:create", args=[self.ticket.pk])).status_code, 403)
