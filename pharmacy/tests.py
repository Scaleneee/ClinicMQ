"""Tests for the Medicine Inventory module.

Run without touching Supabase:
    python manage.py test pharmacy --settings=clinicmq.settings_test
"""

import datetime as dt
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.utils import timezone

from accounts.models import Shift, Staff
from consultation import services as cs
from patients.models import Patient
from pharmacy import services as ps
from pharmacy.models import Medicine, PrescriptionItem
from queueing import services as q

User = get_user_model()
TODAY = dt.date(2026, 11, 4)
NEXT_YEAR = TODAY + dt.timedelta(days=365)


class PharmacyTestCase(TestCase):
    def setUp(self):
        clock = mock.patch("django.utils.timezone.now",
                           return_value=timezone.make_aware(dt.datetime.combine(TODAY, dt.time(10))))
        clock.start()
        self.addCleanup(clock.stop)

        self.nurse = self.staff("Farah Lim", "NURSE")
        self.doc = self.staff("Aisyah Rahman", "DOCTOR")
        self.admin = self.staff("Kumar", "ADMIN")
        self.para = Medicine.objects.create(name="Paracetamol 500mg", category="Analgesic", unit="tablets",
                                            unit_price=Decimal("0.50"), quantity=100, reorder_level=20,
                                            expiry_date=NEXT_YEAR)
        self.syrup = Medicine.objects.create(name="Cough syrup 100ml", category="Cough", unit="bottles",
                                             unit_price=Decimal("8.00"), quantity=5, reorder_level=10,
                                             expiry_date=TODAY + dt.timedelta(days=10))

    def staff(self, name, role):
        email = f"{name.split()[0].lower()}@clinic.my"
        user = User.objects.create_user(username=email, email=email, password="x", role=role)
        return Staff.objects.create(user=user, full_name=name, phone="012-0000000")

    def data(self, **kw):
        d = dict(name="Loratadine 10mg", category="Antihistamine", unit="tablets", unit_price="0.80",
                 quantity="50", reorder_level="10", expiry_date=NEXT_YEAR)
        d.update(kw)
        return d

    def visit(self, items, complete=True):
        """A consultation with these (medicine, quantity) items; the visit is completed by default."""
        Shift.objects.get_or_create(staff=self.doc, shift_date=TODAY, session="MORNING")
        n = Patient.objects.count() + 1
        patient = Patient.objects.create(ic_no=f"900101-14-{5600 + 2 * n + 1}", full_name=f"PATIENT {n}",
                                         gender="M", date_of_birth=dt.date(1990, 1, 1), phone="012-3456789")
        t = q.issue_ticket(issued_by=self.nurse.user, patient=patient, source="WALKIN")
        q.call_next(called_by=self.nurse.user)
        q.start_consultation(started_by=self.doc.user, ticket_id=t.pk)
        c, _ = cs.create_consultation(
            doctor_user=self.doc.user, ticket_id=t.pk, symptoms="Cough", diagnosis="URTI", consult_fee="30",
            items=[{"medicine": m.pk, "dosage": "as directed", "quantity": qty} for m, qty in items])
        if complete:
            q.complete_ticket(completed_by=self.doc.user, ticket_id=t.pk)
        return c


class MedicineCrudTests(PharmacyTestCase):
    def test_nurse_adds_medicine(self):
        m = ps.create_medicine(created_by=self.nurse.user, **self.data(name="  loratadine   10mg "))
        self.assertEqual((m.name, m.unit_price, m.quantity, m.reorder_level),
                         ("loratadine 10mg", Decimal("0.80"), 50, 10))

    def test_only_nurses_add_edit_and_restock(self):
        for user in (self.doc.user, self.admin.user):
            with self.assertRaises(PermissionDenied):
                ps.create_medicine(created_by=user, **self.data())
            with self.assertRaises(PermissionDenied):
                ps.update_medicine(updated_by=user, medicine_id=self.para.pk, **self.data())
            with self.assertRaises(PermissionDenied):
                ps.restock_medicine(restocked_by=user, medicine_id=self.para.pk, add_quantity=5)

    def test_validation(self):
        with self.assertRaises(ValidationError) as e:
            ps.create_medicine(created_by=self.nurse.user, **self.data(
                name="PARACETAMOL 500MG", unit_price="0", quantity="-1", reorder_level="x",
                expiry_date=TODAY, category="", unit=""))
        self.assertEqual(set(e.exception.message_dict),
                         {"name", "unit_price", "quantity", "reorder_level", "expiry_date", "category", "unit"})
        self.assertIn("already in the inventory", e.exception.message_dict["name"][0])

    def test_edit_keeps_own_name_and_old_expiry(self):
        Medicine.objects.filter(pk=self.syrup.pk).update(expiry_date=TODAY - dt.timedelta(days=1))
        self.syrup.refresh_from_db()
        m = ps.update_medicine(updated_by=self.nurse.user, medicine_id=self.syrup.pk, **self.data(
            name="Cough syrup 100ml", unit_price="9.00", expiry_date=self.syrup.expiry_date))
        self.assertEqual(m.unit_price, Decimal("9.00"))
        with self.assertRaises(ValidationError):  # a new past date is still refused
            ps.update_medicine(updated_by=self.nurse.user, medicine_id=self.syrup.pk,
                               **self.data(name="Cough syrup 100ml", expiry_date=TODAY - dt.timedelta(days=5)))

    def test_restock(self):
        m = ps.restock_medicine(restocked_by=self.nurse.user, medicine_id=self.syrup.pk, add_quantity="20",
                                expiry_date=NEXT_YEAR)
        self.assertEqual((m.quantity, m.expiry_date), (25, NEXT_YEAR))
        with self.assertRaises(ValidationError):
            ps.restock_medicine(restocked_by=self.nurse.user, medicine_id=self.syrup.pk, add_quantity=0)

    def test_restock_of_expired_stock_needs_new_expiry(self):
        Medicine.objects.filter(pk=self.syrup.pk).update(expiry_date=TODAY)
        with self.assertRaises(ValidationError) as e:
            ps.restock_medicine(restocked_by=self.nurse.user, medicine_id=self.syrup.pk, add_quantity=10)
        self.assertIn("expiry_date", e.exception.message_dict)

    def test_admin_deletes_unused_medicine_only(self):
        with self.assertRaises(PermissionDenied):
            ps.delete_medicine(deleted_by=self.nurse.user, medicine_id=self.syrup.pk)
        self.visit([(self.para, 10)])
        with self.assertRaises(ValidationError):
            ps.delete_medicine(deleted_by=self.admin.user, medicine_id=self.para.pk)
        self.assertEqual(ps.delete_medicine(deleted_by=self.admin.user, medicine_id=self.syrup.pk),
                         "Cough syrup 100ml")
        self.assertFalse(Medicine.objects.filter(pk=self.syrup.pk).exists())


class ListTests(PharmacyTestCase):
    def test_badges(self):
        self.assertEqual(ps.stock_badges(self.para), [])
        self.assertEqual(ps.stock_badges(self.syrup), [("Low stock", "waiting"), ("Expiring soon", "missed")])
        self.syrup.quantity, self.syrup.expiry_date = 0, TODAY
        self.assertEqual(ps.stock_badges(self.syrup), [("Out of stock", "out"), ("Expired", "out")])

    def test_filters_search_and_counts(self):
        Medicine.objects.create(name="Amoxicillin 250mg", category="Antibiotic", unit="capsules",
                                unit_price=Decimal("1"), quantity=0, expiry_date=NEXT_YEAR)
        names = lambda **kw: [m.name for m in ps.list_medicines(viewed_by=self.doc.user, **kw)]
        self.assertEqual(names(status="low"), ["Amoxicillin 250mg", "Cough syrup 100ml"])
        self.assertEqual(names(status="out"), ["Amoxicillin 250mg"])
        self.assertEqual(names(status="expiring"), ["Cough syrup 100ml"])
        self.assertEqual(names(query="analg"), ["Paracetamol 500mg"])
        self.assertEqual(names(category="antibiotic"), ["Amoxicillin 250mg"])
        self.assertEqual(ps.filter_counts(), {"all": 3, "low": 2, "expiring": 1, "out": 1})

    def test_patients_cannot_view(self):
        patient = User.objects.create_user(username="p@x.my", email="p@x.my", password="x", role="PATIENT")
        with self.assertRaises(PermissionDenied):
            ps.list_medicines(viewed_by=patient)


class DispenseTests(PharmacyTestCase):
    def test_dispense_reduces_stock_and_logs_nurse(self):
        c = self.visit([(self.para, 20), (self.syrup, 1)])
        self.assertEqual(list(ps.pending_dispense()), [c])
        ps.dispense_items(dispensed_by=self.nurse.user, consultation_id=c.pk,
                          medicine_ids=[self.para.pk, self.syrup.pk])
        self.para.refresh_from_db()
        self.syrup.refresh_from_db()
        self.assertEqual((self.para.quantity, self.syrup.quantity), (80, 4))
        item = PrescriptionItem.objects.get(consultation=c, medicine=self.para)
        self.assertTrue(item.dispensed)
        self.assertEqual((item.dispensed_by, item.dispensed_at), (self.nurse, timezone.now()))
        self.assertEqual(list(ps.pending_dispense()), [])

    def test_partial_dispense_then_rest(self):
        c = self.visit([(self.para, 20), (self.syrup, 1)])
        ps.dispense_items(dispensed_by=self.nurse.user, consultation_id=c.pk, medicine_ids=[str(self.para.pk)])
        self.assertEqual(list(ps.pending_dispense()), [c])
        with self.assertRaises(ValidationError) as e:  # only once
            ps.dispense_items(dispensed_by=self.nurse.user, consultation_id=c.pk, medicine_ids=[self.para.pk])
        self.assertIn("already dispensed", e.exception.messages[0])

    def test_not_enough_stock_changes_nothing(self):
        c = self.visit([(self.para, 20), (self.syrup, 5)])
        Medicine.objects.filter(pk=self.syrup.pk).update(quantity=3)
        with self.assertRaises(ValidationError) as e:
            ps.dispense_items(dispensed_by=self.nurse.user, consultation_id=c.pk,
                              medicine_ids=[self.para.pk, self.syrup.pk])
        self.assertEqual(e.exception.messages, ["Not enough stock for Cough syrup 100ml (need 5, have 3)."])
        self.para.refresh_from_db()
        self.assertEqual(self.para.quantity, 100)  # all or nothing
        self.assertFalse(PrescriptionItem.objects.filter(dispensed=True).exists())

    def test_expired_medicine_cannot_be_dispensed(self):
        c = self.visit([(self.syrup, 1)])
        Medicine.objects.filter(pk=self.syrup.pk).update(expiry_date=TODAY)
        with self.assertRaises(ValidationError) as e:
            ps.dispense_items(dispensed_by=self.nurse.user, consultation_id=c.pk, medicine_ids=[self.syrup.pk])
        self.assertIn("expired", e.exception.messages[0])

    def test_rules(self):
        c = self.visit([(self.para, 20)], complete=False)
        with self.assertRaises(ValidationError):  # visit not completed yet
            ps.dispense_items(dispensed_by=self.nurse.user, consultation_id=c.pk, medicine_ids=[self.para.pk])
        self.assertEqual(list(ps.pending_dispense()), [])
        with self.assertRaises(PermissionDenied):
            ps.dispense_items(dispensed_by=self.doc.user, consultation_id=c.pk, medicine_ids=[self.para.pk])
        q.complete_ticket(completed_by=self.doc.user, ticket_id=c.ticket_id)
        with self.assertRaises(ValidationError):  # nothing ticked
            ps.dispense_items(dispensed_by=self.nurse.user, consultation_id=c.pk, medicine_ids=[])
        with self.assertRaises(ValidationError):  # not in this prescription
            ps.dispense_items(dispensed_by=self.nurse.user, consultation_id=c.pk, medicine_ids=[self.syrup.pk])


class MedicineListPageTests(PharmacyTestCase):
    def test_list_with_filter_and_badges(self):
        self.client.force_login(self.nurse.user)
        page = self.client.get("/pharmacy/?filter=low")
        self.assertContains(page, "Cough syrup 100ml")
        self.assertNotContains(page, "Paracetamol 500mg")
        for text in ("Low stock", "Expiring soon", "5 bottles", "Add medicine"):
            self.assertContains(page, text)

    def test_doctor_views_without_actions_and_patient_is_refused(self):
        self.client.force_login(self.doc.user)
        page = self.client.get("/pharmacy/")
        self.assertContains(page, "Paracetamol 500mg")
        self.assertNotContains(page, "Add medicine")
        self.assertNotContains(page, "Restock")
        patient = User.objects.create_user(username="p@x.my", email="p@x.my", password="x", role="PATIENT")
        self.client.force_login(patient)
        self.assertEqual(self.client.get("/pharmacy/").status_code, 403)


class MedicineFormPageTests(PharmacyTestCase):
    def post(self, url, **kw):
        d = self.data(**kw)
        d["expiry_date"] = d["expiry_date"].isoformat()
        return self.client.post(url, d)

    def test_add_and_edit(self):
        self.client.force_login(self.nurse.user)
        self.assertRedirects(self.post("/pharmacy/new/"), "/pharmacy/")
        m = Medicine.objects.get(name="Loratadine 10mg")
        self.assertRedirects(self.post(f"/pharmacy/{m.pk}/edit/", unit_price="1.20"), "/pharmacy/")
        m.refresh_from_db()
        self.assertEqual(m.unit_price, Decimal("1.20"))

    def test_errors_show_on_the_form(self):
        self.client.force_login(self.nurse.user)
        page = self.post("/pharmacy/new/", name="paracetamol 500MG", unit_price="0")
        self.assertContains(page, "is already in the inventory")
        self.assertContains(page, "Unit price must be more than RM 0.")

    def test_doctor_cannot_add(self):
        self.client.force_login(self.doc.user)
        self.assertEqual(self.client.get("/pharmacy/new/").status_code, 403)


class RestockPageTests(PharmacyTestCase):
    def test_restock_page(self):
        self.client.force_login(self.nurse.user)
        url = f"/pharmacy/{self.syrup.pk}/restock/"
        self.assertContains(self.client.get(url), "5 bottles")
        self.assertRedirects(self.client.post(url, {"add_quantity": "30", "expiry_date": ""}), "/pharmacy/")
        self.syrup.refresh_from_db()
        self.assertEqual(self.syrup.quantity, 35)
        page = self.client.post(url, {"add_quantity": "0", "expiry_date": TODAY.isoformat()})
        self.assertContains(page, "Enter how many to add")
        self.assertContains(page, "Expiry date must be in the future.")


class DeletePageTests(PharmacyTestCase):
    def test_admin_deletes_and_sees_blocked_state(self):
        self.visit([(self.para, 10)])
        self.client.force_login(self.admin.user)
        self.assertContains(self.client.get(f"/pharmacy/{self.para.pk}/delete/"), "Used in prescriptions.")
        self.client.post(f"/pharmacy/{self.para.pk}/delete/")
        self.assertTrue(Medicine.objects.filter(pk=self.para.pk).exists())
        self.assertContains(self.client.get(f"/pharmacy/{self.syrup.pk}/delete/"), "Delete Cough syrup 100ml?")
        self.assertRedirects(self.client.post(f"/pharmacy/{self.syrup.pk}/delete/"), "/pharmacy/")
        self.assertFalse(Medicine.objects.filter(pk=self.syrup.pk).exists())

    def test_nurse_cannot_delete(self):
        self.client.force_login(self.nurse.user)
        self.assertEqual(self.client.post(f"/pharmacy/{self.syrup.pk}/delete/").status_code, 403)


class DispensePageTests(PharmacyTestCase):
    def test_list_and_dispense(self):
        c = self.visit([(self.para, 20), (self.syrup, 2)])
        self.client.force_login(self.nurse.user)
        page = self.client.get("/pharmacy/dispense/")
        self.assertContains(page, "Patient 1")
        self.assertContains(page, "2 to dispense")
        page = self.client.get(f"/pharmacy/dispense/{c.pk}/")
        self.assertContains(page, "Mark as dispensed")
        self.assertContains(page, "5 bottles")  # stock left
        self.client.post(f"/pharmacy/dispense/{c.pk}/", {"medicine": [self.para.pk]})
        self.assertContains(self.client.get(f"/pharmacy/dispense/{c.pk}/"), "Dispensed by Farah Lim")
        self.assertRedirects(self.client.post(f"/pharmacy/dispense/{c.pk}/", {"medicine": [self.syrup.pk]}),
                             "/pharmacy/dispense/")
        self.assertContains(self.client.get("/pharmacy/dispense/"), "Nothing to dispense.")

    def test_not_enough_stock_is_shown(self):
        c = self.visit([(self.syrup, 2)])
        Medicine.objects.filter(pk=self.syrup.pk).update(quantity=1)
        self.client.force_login(self.nurse.user)
        page = self.client.get(f"/pharmacy/dispense/{c.pk}/")
        self.assertContains(page, "Not enough stock for Cough syrup 100ml (need 2, have 1).")

    def test_only_nurses_dispense(self):
        c = self.visit([(self.para, 20)])
        self.client.force_login(self.doc.user)
        self.assertEqual(self.client.get("/pharmacy/dispense/").status_code, 403)
        self.assertEqual(self.client.post(f"/pharmacy/dispense/{c.pk}/").status_code, 403)
