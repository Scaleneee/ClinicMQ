"""Tests for the Staff & Schedule module (accounts app).

Run without touching Supabase:
    python manage.py test accounts --settings=clinicmq.settings_test
"""

import datetime as dt
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.utils import timezone

from accounts import services as acc
from accounts.models import Shift, Staff

User = get_user_model()
TODAY = dt.date(2026, 11, 4)  # a Wednesday


class StaffTestCase(TestCase):
    def setUp(self):
        clock = mock.patch("django.utils.timezone.now",
                           return_value=timezone.make_aware(dt.datetime.combine(TODAY, dt.time(10))))
        clock.start()
        self.addCleanup(clock.stop)
        self.admin = self.make_staff("Kumar", "ADMIN")
        self.admin_user = self.admin.user

    def make_staff(self, name, role, **extra):
        email = f"{name.lower().replace(' ', '.')}@clinic.my"
        user = User.objects.create_user(username=email, email=email, password="pw-Strong-123", role=role)
        return Staff.objects.create(user=user, full_name=name, role=role, phone="012-0000000", **extra)

    def add(self, staff, day=TODAY, session="MORNING"):
        return acc.add_shift(added_by=self.admin_user, staff_id=staff.pk, shift_date=day, session=session)


class CreateUpdateStaffTests(StaffTestCase):
    def new(self, **kw):
        data = dict(created_by=self.admin_user, full_name="  Aisyah   Rahman ", email="Aisyah@Clinic.my",
                    role="doctor", phone="0123456789", password="Strong-Pass-123", specialty="General practice")
        data.update(kw)
        return acc.create_staff(**data)

    def test_admin_adds_doctor_with_login(self):
        s = self.new()
        self.assertEqual((s.full_name, s.role, s.phone, s.specialty),
                         ("Aisyah Rahman", "DOCTOR", "012-3456789", "General practice"))
        self.assertEqual((s.user.email, s.user.username, s.user.role), ("aisyah@clinic.my",) * 2 + ("DOCTOR",))
        self.assertTrue(s.user.check_password("Strong-Pass-123"))

    def test_specialty_only_for_doctors(self):
        self.assertIsNone(self.new(role="NURSE", email="farah@clinic.my").specialty)

    def test_validation(self):
        with self.assertRaises(ValidationError) as e:
            self.new(email="kumar@clinic.my", role="CLEANER", phone="123", full_name="", password="123")
        self.assertEqual(set(e.exception.message_dict), {"email", "role", "phone", "full_name", "password"})

    def test_only_admin(self):
        nurse = self.make_staff("Farah", "NURSE")
        with self.assertRaises(PermissionDenied):
            self.new(created_by=nurse.user)

    def test_update_syncs_login_and_role(self):
        s = self.new()
        s = acc.update_staff(updated_by=self.admin_user, staff_id=s.pk, full_name="Aisyah R.",
                             email="dr.aisyah@clinic.my", role="NURSE", phone="019-1112222", specialty="x")
        s.user.refresh_from_db()
        self.assertEqual((s.user.email, s.user.username, s.user.role, s.specialty),
                         ("dr.aisyah@clinic.my", "dr.aisyah@clinic.my", "NURSE", None))

    def test_last_admin_and_own_role_protected(self):
        with self.assertRaisesMessage(ValidationError, "only active admin"):
            acc.update_staff(updated_by=self.admin_user, staff_id=self.admin.pk, full_name="Kumar",
                             email="kumar@clinic.my", role="NURSE", phone="012-0000000")


class DeactivateTests(StaffTestCase):
    def test_deactivated_staff_cannot_log_in_and_reactivate(self):
        nurse = self.make_staff("Farah", "NURSE")
        acc.deactivate_staff(deactivated_by=self.admin_user, staff_id=nurse.pk)
        self.assertFalse(self.client.login(username="farah@clinic.my", password="pw-Strong-123"))
        acc.reactivate_staff(reactivated_by=self.admin_user, staff_id=nurse.pk)
        self.assertTrue(self.client.login(username="farah@clinic.my", password="pw-Strong-123"))

    def test_cannot_deactivate_self_or_last_admin(self):
        with self.assertRaisesMessage(ValidationError, "your own account"):
            acc.deactivate_staff(deactivated_by=self.admin_user, staff_id=self.admin.pk)
        other_admin = self.make_staff("Siti", "ADMIN")
        acc.deactivate_staff(deactivated_by=other_admin.user, staff_id=self.admin.pk)  # 2 admins: fine
        with self.assertRaises(ValidationError):  # now Siti is the last one (and herself)
            acc.deactivate_staff(deactivated_by=other_admin.user, staff_id=other_admin.pk)

    def test_deactivated_doctor_is_not_on_duty(self):
        doc = self.make_staff("Aisyah", "DOCTOR")
        self.add(doc)
        acc.deactivate_staff(deactivated_by=self.admin_user, staff_id=doc.pk)
        self.assertIsNone(acc.doctor_on_duty(TODAY, "MORNING"))

    def test_reactivate_blocked_if_another_doctor_took_the_session(self):
        a, b = self.make_staff("Aisyah", "DOCTOR"), self.make_staff("Tan", "DOCTOR")
        self.add(a)
        acc.deactivate_staff(deactivated_by=self.admin_user, staff_id=a.pk)
        self.add(b)
        with self.assertRaisesMessage(ValidationError, "Dr. Tan is already on duty"):
            acc.reactivate_staff(reactivated_by=self.admin_user, staff_id=a.pk)


class ShiftTests(StaffTestCase):
    def setUp(self):
        super().setUp()
        self.doc = self.make_staff("Aisyah Rahman", "DOCTOR")
        self.doc2 = self.make_staff("Tan Wei Ming", "DOCTOR")
        self.nurse = self.make_staff("Farah Lim", "NURSE")
        self.nurse2 = self.make_staff("Mei Ling", "NURSE")

    def test_one_doctor_per_session(self):
        self.add(self.doc)
        with self.assertRaisesMessage(ValidationError, "Dr. Aisyah Rahman is already on duty for this session."):
            self.add(self.doc2)
        self.add(self.doc2, session="NIGHT")  # other session is fine

    def test_many_nurses_but_each_works_a_session_once(self):
        self.add(self.nurse)
        self.add(self.nurse2)
        with self.assertRaisesMessage(ValidationError, "Farah Lim already works this session."):
            self.add(self.nurse)

    def test_no_past_shifts_and_past_is_read_only(self):
        with self.assertRaisesMessage(ValidationError, "today or later"):
            self.add(self.nurse, day=TODAY - dt.timedelta(days=1))
        old = Shift.objects.create(staff=self.nurse, shift_date=TODAY - dt.timedelta(days=1), session="MORNING")
        with self.assertRaisesMessage(ValidationError, "history"):
            acc.remove_shift(removed_by=self.admin_user, shift_id=old.pk)

    def test_edit_and_remove(self):
        s = self.add(self.doc)
        s = acc.update_shift(updated_by=self.admin_user, shift_id=s.pk, staff_id=self.doc.pk,
                             shift_date=TODAY + dt.timedelta(days=1), session="NIGHT")
        self.assertEqual((s.shift_date, s.session), (TODAY + dt.timedelta(days=1), "NIGHT"))
        acc.remove_shift(removed_by=self.admin_user, shift_id=s.pk)
        self.assertFalse(Shift.objects.exists())

    def test_cannot_roster_deactivated_staff(self):
        acc.deactivate_staff(deactivated_by=self.admin_user, staff_id=self.nurse.pk)
        with self.assertRaisesMessage(ValidationError, "deactivated"):
            self.add(self.nurse)

    def test_week_roster_monday_to_sunday_doctors_first(self):
        self.add(self.nurse)
        self.add(self.doc)
        self.add(self.nurse2, day=TODAY + dt.timedelta(days=2), session="NIGHT")
        week = acc.week_roster(acc.week_start(TODAY), viewed_by=self.nurse.user)
        self.assertEqual(week[0]["date"], dt.date(2026, 11, 2))          # Monday
        wed = week[2]
        self.assertTrue(wed["is_today"])
        self.assertEqual([s.staff.full_name for s in wed["sessions"]["MORNING"]], ["Aisyah Rahman", "Farah Lim"])
        self.assertEqual([s.staff.full_name for s in week[4]["sessions"]["NIGHT"]], ["Mei Ling"])

    def test_only_admin_manages_shifts(self):
        with self.assertRaises(PermissionDenied):
            acc.add_shift(added_by=self.nurse.user, staff_id=self.nurse.pk, shift_date=TODAY, session="MORNING")


# ---------------------------------------------------------------------------
# Screens
# ---------------------------------------------------------------------------
from django.urls import reverse  # noqa: E402


class StaffListScreenTests(StaffTestCase):
    def setUp(self):
        super().setUp()
        self.doc = self.make_staff("Aisyah Rahman", "DOCTOR", specialty="General practice")
        self.nurse = self.make_staff("Farah Lim", "NURSE")

    def test_list_filters_and_search(self):
        self.client.force_login(self.admin_user)
        page = self.client.get(reverse("staff_list"))
        self.assertContains(page, "Dr. Aisyah Rahman")
        self.assertContains(page, 'Doctors <span class="cmq-pill-count">1</span>')
        page = self.client.get(reverse("staff_list") + "?role=nurses")
        self.assertContains(page, "Farah Lim")
        self.assertNotContains(page, "Aisyah")
        page = self.client.get(reverse("staff_list") + "?q=farah.lim@clinic")
        self.assertContains(page, "Farah Lim")
        self.assertNotContains(page, "Aisyah")

    def test_all_staff_can_view_but_patients_cannot(self):
        self.client.force_login(self.nurse.user)
        page = self.client.get(reverse("staff_list"))
        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, "Add staff")
        patient = User.objects.create_user(username="p@x.my", email="p@x.my", password="x", role="PATIENT")
        self.client.force_login(patient)
        self.assertEqual(self.client.get(reverse("staff_list")).status_code, 403)


class StaffFormScreenTests(StaffTestCase):
    VALID = {"full_name": "Aisyah Rahman", "email": "aisyah@clinic.my", "role": "DOCTOR",
             "phone": "0123456789", "specialty": "General practice",
             "password1": "Strong-Pass-123", "password2": "Strong-Pass-123"}

    def test_add_staff_then_they_can_log_in(self):
        self.client.force_login(self.admin_user)
        page = self.client.post(reverse("staff_create"), self.VALID, follow=True)
        self.assertContains(page, "Dr. Aisyah Rahman was added.")
        self.client.logout()
        self.assertTrue(self.client.login(username="aisyah@clinic.my", password="Strong-Pass-123"))

    def test_add_shows_errors(self):
        self.client.force_login(self.admin_user)
        page = self.client.post(reverse("staff_create"), {**self.VALID, "email": "kumar@clinic.my",
                                                          "password1": "123", "password2": "123"})
        self.assertContains(page, "An account with this email already exists.")
        self.assertContains(page, "too short")
        page = self.client.post(reverse("staff_create"), {**self.VALID, "password2": "different"})
        self.assertContains(page, "do not match")

    def test_edit_staff(self):
        nurse = self.make_staff("Farah Lim", "NURSE")
        self.client.force_login(self.admin_user)
        page = self.client.get(reverse("staff_edit", args=[nurse.pk]))
        self.assertContains(page, "Upcoming shifts")
        self.assertNotContains(page, "Temporary password")
        page = self.client.post(reverse("staff_edit", args=[nurse.pk]),
                                {"full_name": "Farah Lim", "email": "farah@clinic.my", "role": "NURSE",
                                 "phone": "019-1112222", "specialty": ""}, follow=True)
        self.assertContains(page, "Farah Lim&#x27;s details were saved.")
        nurse.refresh_from_db()
        self.assertEqual((nurse.phone, nurse.user.email), ("019-1112222", "farah@clinic.my"))

    def test_only_admin(self):
        nurse = self.make_staff("Farah Lim", "NURSE")
        self.client.force_login(nurse.user)
        self.assertEqual(self.client.get(reverse("staff_create")).status_code, 403)
        self.assertEqual(self.client.get(reverse("staff_edit", args=[nurse.pk])).status_code, 403)


class DeactivateScreenTests(StaffTestCase):
    def test_deactivate_and_reactivate_from_list(self):
        nurse = self.make_staff("Farah Lim", "NURSE")
        self.client.force_login(self.admin_user)
        page = self.client.get(reverse("staff_list"))
        self.assertContains(page, "Deactivate Farah Lim?")
        self.assertNotContains(page, "Deactivate Kumar?")  # not on your own row

        page = self.client.post(reverse("staff_deactivate", args=[nurse.pk]), follow=True)
        self.assertContains(page, "Farah Lim was deactivated and can no longer log in.")
        self.assertContains(page, "Reactivate")
        page = self.client.post(reverse("staff_reactivate", args=[nurse.pk]), follow=True)
        self.assertContains(page, "Farah Lim was reactivated")

    def test_cannot_deactivate_self(self):
        self.client.force_login(self.admin_user)
        page = self.client.post(reverse("staff_deactivate", args=[self.admin.pk]), follow=True)
        self.assertContains(page, "can&#x27;t deactivate your own account")

    def test_get_is_not_allowed(self):
        nurse = self.make_staff("Farah Lim", "NURSE")
        self.client.force_login(self.admin_user)
        self.assertEqual(self.client.get(reverse("staff_deactivate", args=[nurse.pk])).status_code, 405)


class RosterScreenTests(StaffTestCase):
    def setUp(self):
        super().setUp()
        self.doc = self.make_staff("Aisyah Rahman", "DOCTOR")
        self.nurse = self.make_staff("Farah Lim", "NURSE")
        self.add(self.doc)
        self.add(self.nurse)

    def test_week_grid(self):
        self.client.force_login(self.nurse.user)  # everyone on the staff can view
        page = self.client.get(reverse("roster"))
        self.assertContains(page, "02/11/2026 – 08/11/2026")
        self.assertContains(page, "Dr. Aisyah Rahman")
        self.assertContains(page, "Nurse Farah Lim")
        self.assertContains(page, "9:00 AM – 1:00 PM")
        self.assertContains(page, "No doctor")        # e.g. tonight
        self.assertContains(page, 'class="is-today')

    def test_week_navigation(self):
        self.client.force_login(self.admin_user)
        page = self.client.get(reverse("roster") + "?week=2026-11-12")  # any day -> its Monday
        self.assertContains(page, "09/11/2026 – 15/11/2026")
        self.assertContains(page, "?week=2026-11-02")  # previous
        self.assertContains(page, "This week")
        page = self.client.get(reverse("roster") + "?week=2026-11-30")
        self.assertContains(page, "30/11/2026 – 06/12/2026")

    def test_deactivated_staff_greyed_out(self):
        acc.deactivate_staff(deactivated_by=self.admin_user, staff_id=self.nurse.pk)
        self.client.force_login(self.admin_user)
        self.assertContains(self.client.get(reverse("roster")), "cmq-chip-inactive")


class ShiftScreenTests(StaffTestCase):
    def setUp(self):
        super().setUp()
        self.doc = self.make_staff("Aisyah Rahman", "DOCTOR")
        self.doc2 = self.make_staff("Tan Wei Ming", "DOCTOR")
        self.client.force_login(self.admin_user)

    def test_add_shift_from_roster_cell(self):
        page = self.client.get(reverse("roster"))
        self.assertContains(page, "?date=2026-11-04&session=MORNING")  # quick add link
        page = self.client.post(reverse("shift_create"),
                                {"staff": self.doc.pk, "shift_date": "2026-11-04", "session": "MORNING"}, follow=True)
        self.assertContains(page, "Dr. Aisyah Rahman added to Wed 04/11/2026 (morning).")
        self.assertEqual(acc.doctor_on_duty(TODAY, "MORNING"), self.doc)

    def test_second_doctor_shows_ui_md_error(self):
        self.add(self.doc)
        page = self.client.post(reverse("shift_create"),
                                {"staff": self.doc2.pk, "shift_date": "2026-11-04", "session": "MORNING"})
        self.assertContains(page, "Dr. Aisyah Rahman is already on duty for this session.")

    def test_edit_and_remove(self):
        shift = self.add(self.doc)
        page = self.client.post(reverse("shift_edit", args=[shift.pk]),
                                {"staff": self.doc.pk, "shift_date": "2026-11-05", "session": "NIGHT"}, follow=True)
        self.assertContains(page, "Shift saved.")
        shift.refresh_from_db()
        self.assertEqual((shift.shift_date, shift.session), (dt.date(2026, 11, 5), "NIGHT"))
        page = self.client.post(reverse("shift_delete", args=[shift.pk]), follow=True)
        self.assertContains(page, "Dr. Aisyah Rahman removed from Thu 05/11/2026.")
        self.assertFalse(Shift.objects.exists())

    def test_past_shift_cannot_be_edited(self):
        old = Shift.objects.create(staff=self.doc, shift_date=TODAY - dt.timedelta(days=1), session="MORNING")
        page = self.client.get(reverse("shift_edit", args=[old.pk]), follow=True)
        self.assertContains(page, "kept as history")

    def test_nurse_cannot_manage_shifts(self):
        nurse = self.make_staff("Farah Lim", "NURSE")
        self.client.force_login(nurse.user)
        self.assertEqual(self.client.get(reverse("shift_create")).status_code, 403)
        self.assertNotContains(self.client.get(reverse("roster")), "Add shift")


# ---------------------------------------------------------------------------
# Dashboards (nurse, admin)
# ---------------------------------------------------------------------------
from decimal import Decimal  # noqa: E402

from billing.models import Bill, BillItem  # noqa: E402
from consultation.models import Consultation  # noqa: E402
from patients.models import Patient  # noqa: E402
from pharmacy.models import Medicine, PrescriptionItem  # noqa: E402
from queueing import services as q  # noqa: E402
from queueing.models import QueueTicket  # noqa: E402


class DashboardTestCase(StaffTestCase):
    """A small clinic day: Dr. Aisyah on the morning shift, a few tickets, medicines and bills."""

    def setUp(self):
        super().setUp()
        self.doc = self.make_staff("Aisyah Rahman", "DOCTOR")
        self.nurse = self.make_staff("Farah Lim", "NURSE")
        self.add(self.doc)
        self.patients = [Patient.objects.create(ic_no=f"9001{n:02d}-14-56{n:02d}", full_name=f"PATIENT {n}",
                                                gender="M" if n % 2 else "F", date_of_birth=dt.date(1990, 1, n),
                                                phone="012-3456789") for n in range(1, 5)]
        self.tickets = [q.issue_ticket(issued_by=self.nurse.user, patient=p, source="WALKIN") for p in self.patients]
        # one finished visit with an unpaid bill and an undispensed prescription
        done = self.tickets[0]
        q.call_next(called_by=self.nurse.user)
        q.start_consultation(started_by=self.doc.user, ticket_id=done.pk)
        q.complete_ticket(completed_by=self.doc.user, ticket_id=done.pk)
        c = Consultation.objects.create(ticket=done, doctor=self.doc, symptoms="Fever", diagnosis="Viral fever",
                                        consult_fee=Decimal("30"))
        self.para = Medicine.objects.create(name="Paracetamol 500mg", category="Analgesic", unit="tablets",
                                            unit_price=Decimal("0.50"), quantity=8, reorder_level=10,
                                            expiry_date=TODAY + dt.timedelta(days=365))
        Medicine.objects.create(name="Cough syrup 100ml", category="Cough", unit="bottles", unit_price=Decimal("8"),
                                quantity=40, expiry_date=TODAY + dt.timedelta(days=10))
        Medicine.objects.create(name="Loratadine 10mg", category="Antihistamine", unit="tablets",
                                unit_price=Decimal("1"), quantity=200, expiry_date=TODAY + dt.timedelta(days=365))
        PrescriptionItem.objects.create(consultation=c, medicine=self.para, dosage="2 tabs", quantity=6)
        self.bill = Bill.objects.create(bill_no="B-20261104-001", consultation=c, created_by=self.nurse)
        BillItem.objects.create(bill=self.bill, item_type="CONSULTATION", description="Consultation",
                                quantity=1, unit_price=Decimal("30"))
        BillItem.objects.create(bill=self.bill, item_type="MEDICINE", medicine=self.para,
                                description="Paracetamol 500mg", quantity=6, unit_price=Decimal("0.50"))


class NurseDashboardTests(DashboardTestCase):
    def test_nurse_dashboard(self):
        self.client.force_login(self.nurse.user)
        page = self.client.get(reverse("dashboard"))
        html = page.content.decode()
        self.assertContains(page, "Welcome, Nurse Farah Lim")
        self.assertContains(page, "Morning session")
        self.assertContains(page, "Dr. Aisyah Rahman")
        self.assertContains(page, "Online numbers open until 12:30 PM")
        stats = page.context["stats"]
        self.assertEqual(stats, {"today": 4, "checked_in": 3, "to_dispense": 1, "low_stock": 1})
        self.assertContains(page, "Patient 2")                        # next in line
        self.assertIn("Low stock", html)                              # Paracetamol
        self.assertIn("Expiring soon", html)                          # Cough syrup
        self.assertNotIn("Loratadine", html)                          # fine
        self.assertContains(page, "RM 33.00")                         # unpaid bill total

    def test_empty_day(self):
        self.client.force_login(self.nurse.user)
        Bill.objects.all().delete()
        self.assertContains(self.client.get(reverse("dashboard")), "No unpaid bills.")


class AdminDashboardTests(DashboardTestCase):
    def test_admin_dashboard(self):
        # pay the bill: revenue counts paid bills only
        Bill.objects.filter(pk=self.bill.pk).update(status="PAID", payment_method="CASH",
                                                    amount_paid=Decimal("50"), paid_at=timezone.now())
        self.client.force_login(self.admin_user)
        page = self.client.get(reverse("dashboard"))
        self.assertContains(page, "Welcome, Kumar")
        stats = page.context["stats"]
        self.assertEqual((stats["patients_today"], stats["revenue_today"], stats["unpaid"], stats["low_stock"]),
                         (4, Decimal("33.00"), 0, 1))
        self.assertContains(page, "RM 33.00")
        self.assertContains(page, "This week's roster")
        self.assertContains(page, "Dr. Aisyah Rahman")
        self.assertContains(page, "No doctor")           # e.g. tonight
        self.assertContains(page, "B-20261104-001")       # recent bills
        self.assertContains(page, "Cash")

    def test_unpaid_bill_counts_and_no_revenue(self):
        self.client.force_login(self.admin_user)
        stats = self.client.get(reverse("dashboard")).context["stats"]
        self.assertEqual((stats["unpaid"], stats["revenue_label"]), (1, "RM 0.00"))



class DoctorDashboardTests(DashboardTestCase):
    def test_doctor_dashboard(self):
        self.client.force_login(self.doc.user)
        page = self.client.get(reverse("dashboard"))
        self.assertTemplateUsed(page, "accounts/dashboard_doctor.html")
        self.assertContains(page, "Welcome, Dr. Aisyah Rahman")
        self.assertContains(page, "on duty this morning session")
        stats = page.context["stats"]
        self.assertEqual((stats["waiting"], stats["seen"]), (3, 1))
        self.assertEqual(stats["next_shift"].shift_date, TODAY)
        self.assertContains(page, "Open doctor console")
        self.assertContains(page, "Viral fever")                 # recent consultation
        self.assertNotContains(page, "Visits waiting for your notes")

    def test_reminder_for_visits_without_notes(self):
        t = self.tickets[1]
        q.call_next(called_by=self.nurse.user)
        q.start_consultation(started_by=self.doc.user, ticket_id=t.pk)
        self.client.force_login(self.doc.user)
        page = self.client.get(reverse("dashboard"))
        self.assertContains(page, "Visits waiting for your notes")
        self.assertContains(page, reverse("consultation:create", args=[t.pk]))

    def test_other_doctor_not_on_duty(self):
        other = self.make_staff("Tan Wei Ming", "DOCTOR")
        self.client.force_login(other.user)
        page = self.client.get(reverse("dashboard"))
        self.assertContains(page, "Dr. Aisyah Rahman is on duty")
        self.assertEqual(page.context["stats"]["seen"], 0)
