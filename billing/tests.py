"""Tests for the Billing module.

Run without touching Supabase:
    python manage.py test billing --settings=clinicmq.settings_test
"""

import datetime as dt
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.utils import timezone

from accounts.models import Shift, Staff
from billing import services as bs
from billing.models import Bill
from consultation import services as cs
from patients.models import Patient
from pharmacy.models import Medicine
from queueing import services as q

User = get_user_model()
TODAY = dt.date(2026, 11, 4)
NEXT_YEAR = TODAY + dt.timedelta(days=365)


class BillingTestCase(TestCase):
    def setUp(self):
        self.clock = mock.patch("django.utils.timezone.now",
                                return_value=timezone.make_aware(dt.datetime.combine(TODAY, dt.time(10))))
        self.clock.start()
        self.addCleanup(self.clock.stop)

        self.nurse = self.staff("Farah Lim", "NURSE")
        self.doc = self.staff("Aisyah Rahman", "DOCTOR")
        self.admin = self.staff("Kumar", "ADMIN")
        Shift.objects.create(staff=self.doc, shift_date=TODAY, session="MORNING")
        self.para = Medicine.objects.create(name="Paracetamol 500mg", category="Analgesic", unit="tablets",
                                            unit_price=Decimal("0.50"), quantity=100, expiry_date=NEXT_YEAR)
        self.syrup = Medicine.objects.create(name="Cough syrup 100ml", category="Cough", unit="bottles",
                                             unit_price=Decimal("8.00"), quantity=10, expiry_date=NEXT_YEAR)

    def staff(self, name, role):
        email = f"{name.split()[0].lower()}@clinic.my"
        user = User.objects.create_user(username=email, email=email, password="x", role=role)
        return Staff.objects.create(user=user, full_name=name, role=role, phone="012-0000000")

    def visit(self, items=(), fee="30", complete=True, user=None):
        """A consultation with (medicine, quantity) items; the visit is completed by default."""
        n = Patient.objects.count() + 1
        patient = Patient.objects.create(ic_no=f"900101-14-{5600 + 2 * n + 1}", full_name=f"PATIENT {n}",
                                         gender="M", date_of_birth=dt.date(1990, 1, 1), phone="012-3456789",
                                         user=user)
        t = q.issue_ticket(issued_by=self.nurse.user, patient=patient, source="WALKIN")
        q.call_next(called_by=self.nurse.user)
        q.start_consultation(started_by=self.doc.user, ticket_id=t.pk)
        c, _ = cs.create_consultation(
            doctor_user=self.doc.user, ticket_id=t.pk, symptoms="Cough", diagnosis="URTI", consult_fee=fee,
            items=[{"medicine": m.pk, "dosage": "as directed", "quantity": qty} for m, qty in items])
        if complete:
            q.complete_ticket(completed_by=self.doc.user, ticket_id=t.pk)
        return c

    def bill(self, **kw):
        c = self.visit(**kw)
        return bs.create_bill(created_by=self.nurse.user, consultation_id=c.pk)


class CreateBillTests(BillingTestCase):
    def test_bill_has_fee_and_medicines(self):
        c = self.visit([(self.para, 20), (self.syrup, 1)])
        self.assertEqual(list(bs.ready_to_bill()), [c])
        bill = bs.create_bill(created_by=self.nurse.user, consultation_id=c.pk)
        self.assertEqual((bill.bill_no, bill.status, bill.created_by), ("B-20261104-001", "UNPAID", self.nurse))
        self.assertEqual([(i.description, i.quantity, i.unit_price) for i in bill.items.order_by("pk")], [
            ("Consultation fee", 1, Decimal("30.00")),
            ("Cough syrup 100ml", 1, Decimal("8.00")),
            ("Paracetamol 500mg", 20, Decimal("0.50")),
        ])
        self.assertEqual(bill.total, Decimal("48.00"))
        self.assertEqual(list(bs.ready_to_bill()), [])
        self.assertEqual(self.bill().bill_no, "B-20261104-002")

    def test_price_is_kept_when_medicine_price_changes(self):
        bill = self.bill(items=[(self.para, 10)])
        Medicine.objects.filter(pk=self.para.pk).update(unit_price=Decimal("2.00"))
        self.assertEqual(bill.total, Decimal("35.00"))

    def test_one_bill_per_consultation(self):
        bill = self.bill()
        with self.assertRaises(ValidationError) as e:
            bs.create_bill(created_by=self.nurse.user, consultation_id=bill.consultation_id)
        self.assertIn(bill.bill_no, e.exception.messages[0])

    def test_rules(self):
        c = self.visit(complete=False)
        with self.assertRaises(ValidationError):  # still with the doctor
            bs.create_bill(created_by=self.nurse.user, consultation_id=c.pk)
        for user in (self.doc.user, self.admin.user):
            with self.assertRaises(PermissionDenied):
                bs.create_bill(created_by=user, consultation_id=c.pk)

    def test_billed_consultation_is_locked(self):
        bill = self.bill(items=[(self.para, 10)])
        self.assertTrue(cs.is_billed(bill.consultation))
        with self.assertRaises(ValidationError):
            cs.delete_consultation(deleted_by=self.admin.user, consultation_id=bill.consultation_id)


class PaymentTests(BillingTestCase):
    def test_cash_with_change(self):
        bill = self.bill(items=[(self.para, 20)])  # RM 40.00
        bill = bs.record_payment(recorded_by=self.nurse.user, bill_id=bill.pk, method="CASH", amount_received="50")
        self.assertEqual((bill.status, bill.amount_paid, bs.change_for(bill)), ("PAID", Decimal("50.00"), Decimal("10.00")))
        self.assertEqual(bill.paid_at, timezone.now())

    def test_cash_less_than_total(self):
        bill = self.bill()
        with self.assertRaises(ValidationError) as e:
            bs.record_payment(recorded_by=self.nurse.user, bill_id=bill.pk, method="CASH", amount_received="29.99")
        self.assertEqual(e.exception.message_dict, {"amount_received": ["Amount paid is less than the total."]})

    def test_card_pays_total_and_method_required(self):
        bill = self.bill()
        with self.assertRaises(ValidationError) as e:
            bs.record_payment(recorded_by=self.nurse.user, bill_id=bill.pk, method="")
        self.assertIn("method", e.exception.message_dict)
        bill = bs.record_payment(recorded_by=self.nurse.user, bill_id=bill.pk, method="EWALLET")
        self.assertEqual((bill.amount_paid, bs.change_for(bill)), (Decimal("30.00"), None))
        with self.assertRaises(ValidationError):  # already paid
            bs.record_payment(recorded_by=self.nurse.user, bill_id=bill.pk, method="CARD")

    def test_no_payment_on_void_bill(self):
        bill = self.bill()
        bs.void_bill(voided_by=self.admin.user, bill_id=bill.pk, reason="Wrong patient")
        with self.assertRaises(ValidationError) as e:
            bs.record_payment(recorded_by=self.nurse.user, bill_id=bill.pk, method="CARD")
        self.assertIn("void", e.exception.messages[0])

    def test_only_nurses_record_payment(self):
        bill = self.bill()
        with self.assertRaises(PermissionDenied):
            bs.record_payment(recorded_by=self.admin.user, bill_id=bill.pk, method="CARD")


class VoidTests(BillingTestCase):
    def test_void_needs_reason_and_admin(self):
        bill = self.bill()
        with self.assertRaises(PermissionDenied):
            bs.void_bill(voided_by=self.nurse.user, bill_id=bill.pk, reason="x")
        with self.assertRaises(ValidationError) as e:
            bs.void_bill(voided_by=self.admin.user, bill_id=bill.pk, reason="   ")
        self.assertIn("reason", e.exception.message_dict)
        bill = bs.void_bill(voided_by=self.admin.user, bill_id=bill.pk, reason="  Billed  twice ")
        self.assertEqual((bill.status, bill.void_reason), ("VOID", "Billed twice"))
        with self.assertRaises(ValidationError):
            bs.void_bill(voided_by=self.admin.user, bill_id=bill.pk, reason="again")


class ReadTests(BillingTestCase):
    def test_list_filters_and_counts(self):
        b1 = self.bill()
        b2 = self.bill()
        bs.record_payment(recorded_by=self.nurse.user, bill_id=b2.pk, method="CARD")
        ids = lambda **kw: [b.pk for b in bs.list_bills(viewed_by=self.admin.user, **kw)]
        self.assertEqual(ids(status="unpaid"), [b1.pk])
        self.assertEqual(ids(status="paid"), [b2.pk])
        self.assertEqual(ids(query="patient 2"), [b2.pk])
        self.assertEqual(ids(query="B-20261104-001"), [b1.pk])
        self.assertEqual(ids(day=TODAY + dt.timedelta(days=1)), [])
        self.assertEqual(bs.status_counts(), {"all": 2, "unpaid": 1, "paid": 1, "void": 0})
        with self.assertRaises(PermissionDenied):
            bs.list_bills(viewed_by=self.doc.user)

    def test_patient_sees_only_own_bills(self):
        siti = User.objects.create_user(username="siti@x.my", email="siti@x.my", password="x", role="PATIENT")
        mine = self.bill(user=siti)
        other = self.bill()
        self.assertEqual(list(bs.bills_for_patient(siti)), [mine])
        self.assertTrue(bs.can_view(siti, mine))
        self.assertFalse(bs.can_view(siti, other))
        self.assertTrue(bs.can_view(self.nurse.user, other))
        self.assertFalse(bs.can_view(self.doc.user, other))

    def test_sales_summary(self):
        b1 = self.bill(items=[(self.para, 20)])   # 40.00 cash
        b2 = self.bill(items=[(self.syrup, 2)])   # 46.00 card
        b3 = self.bill()                           # void
        bs.record_payment(recorded_by=self.nurse.user, bill_id=b1.pk, method="CASH", amount_received="50")
        bs.record_payment(recorded_by=self.nurse.user, bill_id=b2.pk, method="CARD")
        bs.void_bill(voided_by=self.admin.user, bill_id=b3.pk, reason="Test")
        s = bs.sales_summary(viewed_by=self.admin.user, start=TODAY - dt.timedelta(days=1), end=TODAY)
        self.assertEqual((s["revenue"], s["paid_count"], s["average"], s["void_count"]),
                         (Decimal("86.00"), 2, Decimal("43.00"), 1))
        self.assertEqual([(d["date"], d["bills"], d["revenue"]) for d in s["days"]],
                         [(TODAY - dt.timedelta(days=1), 0, Decimal("0")), (TODAY, 2, Decimal("86.00"))])
        self.assertEqual([(m["method"], m["revenue"]) for m in s["by_method"]],
                         [("Card", Decimal("46.00")), ("Cash", Decimal("40.00"))])
        self.assertEqual([(m["description"], m["sold"]) for m in s["top_medicines"]],
                         [("Paracetamol 500mg", 20), ("Cough syrup 100ml", 2)])
        with self.assertRaises(PermissionDenied):
            bs.sales_summary(viewed_by=self.nurse.user, start=TODAY, end=TODAY)
        with self.assertRaises(ValidationError):
            bs.sales_summary(viewed_by=self.admin.user, start=TODAY, end=TODAY - dt.timedelta(days=1))


class BillPageTests(BillingTestCase):
    def test_list_with_ready_to_bill_and_filters(self):
        waiting = self.visit()
        bill = self.bill(items=[(self.para, 20)])
        self.client.force_login(self.nurse.user)
        page = self.client.get("/billing/")
        self.assertContains(page, "Ready to bill")
        self.assertContains(page, waiting.ticket.patient.full_name.title())
        self.assertContains(page, bill.bill_no)
        self.assertContains(page, "RM 40.00")
        self.assertNotContains(self.client.get("/billing/?status=paid"), bill.bill_no)

    def test_detail_for_staff_and_owner_only(self):
        siti = User.objects.create_user(username="siti@x.my", email="siti@x.my", password="x", role="PATIENT")
        bill = self.bill(items=[(self.para, 20)], user=siti)
        self.client.force_login(self.admin.user)
        page = self.client.get(f"/billing/{bill.pk}/")
        for text in ("Bill B-20261104-001", "Consultation fee", "Paracetamol 500mg", "RM 40.00", "Unpaid"):
            self.assertContains(page, text)
        self.client.force_login(siti)
        self.assertEqual(self.client.get(f"/billing/{bill.pk}/").status_code, 200)
        self.assertEqual(self.client.get("/billing/").status_code, 403)
        other = self.bill()
        self.assertEqual(self.client.get(f"/billing/{other.pk}/").status_code, 403)
        self.client.force_login(self.doc.user)
        self.assertEqual(self.client.get(f"/billing/{bill.pk}/").status_code, 403)
