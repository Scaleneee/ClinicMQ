"""Tests for queueing/services.py (queue rules R1–R12 in DESC.md §5).

Run without touching Supabase:
    python manage.py test queueing --settings=clinicmq.settings_test
"""

import datetime as dt
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.utils import timezone

from accounts.models import Shift, Staff
from patients.models import Patient
from queueing import services as q
from queueing.models import QueueTicket

User = get_user_model()
DAY = dt.date(2026, 11, 4)  # morning session 9:00 AM – 1:00 PM, online cut-off 12:30 PM


def at(h, m=0, s=0, day=DAY):
    return timezone.make_aware(dt.datetime.combine(day, dt.time(h, m, s)))


class QueueTestCase(TestCase):
    def setUp(self):
        self.nurse = User.objects.create_user(username="nurse", email="nurse@x.my", password="x", role="NURSE")
        self.doctor_user = User.objects.create_user(username="doc", email="doc@x.my", password="x", role="DOCTOR")
        self.doctor = Staff.objects.create(user=self.doctor_user, full_name="Aisyah Rahman",
                                           role="DOCTOR", phone="012-0000000")
        Shift.objects.create(staff=self.doctor, shift_date=DAY, session="MORNING")
        self.users, self.patients = {}, {}

    def patient(self, n):
        """Patient n with a login (IC and DOB don't matter for the queue)."""
        if n not in self.patients:
            u = User.objects.create_user(username=f"p{n}", email=f"p{n}@x.my", password="x", role="PATIENT")
            self.users[n] = u
            self.patients[n] = Patient.objects.create(
                user=u, ic_no=f"9001{n:02d}-14-56{n:02d}", full_name=f"P{n}", gender="F",
                date_of_birth=dt.date(1990, 1, n), phone="012-3456789")
        return self.patients[n]

    def take(self, n, now=None):
        p = self.patient(n)
        return q.issue_ticket(issued_by=self.users[n], patient=p, source="ONLINE", now=now or at(9, 0, n))

    def check_in(self, ticket, now=None):
        return q.check_in(checked_in_by=self.nurse, ticket_id=ticket.pk, now=now or at(9, 10))

    def line(self):
        return [t.queue_no for t in q.waiting_line(DAY, "MORNING")]

    def serve(self, now):
        """Call next, start and complete; returns the ticket."""
        t = q.call_next(called_by=self.nurse, now=now)
        q.start_consultation(started_by=self.doctor_user, ticket_id=t.pk, now=now)
        return q.complete_ticket(completed_by=self.doctor_user, ticket_id=t.pk, now=now + dt.timedelta(minutes=8))


class IssueTicketTests(QueueTestCase):
    def test_numbers_start_at_001_and_go_up(self):  # R1, R2
        a = self.take(1)
        b = q.issue_ticket(issued_by=self.nurse, patient=self.patient(2), source="WALKIN", now=at(9, 5))
        self.assertEqual((a.queue_no, b.queue_no), (1, 2))
        self.assertEqual(a.status, "WAITING")
        self.assertEqual(b.status, "CHECKED_IN")  # walk-ins are checked in straight away
        self.assertEqual(a.doctor, self.doctor)

    def test_numbers_reset_the_next_day(self):  # R1
        self.take(1)
        Shift.objects.create(staff=self.doctor, shift_date=DAY + dt.timedelta(days=1), session="MORNING")
        t = q.issue_ticket(issued_by=self.nurse, patient=self.patient(2), source="WALKIN",
                           now=at(9, 0, day=DAY + dt.timedelta(days=1)))
        self.assertEqual(t.queue_no, 1)

    def test_one_open_ticket_per_patient_per_day(self):  # R3
        self.take(1)
        with self.assertRaisesMessage(ValidationError, "already has a queue number today"):
            self.take(1, now=at(9, 30))

    def test_closed_outside_sessions(self):  # R4
        with self.assertRaisesMessage(ValidationError, "The clinic is closed now"):
            self.take(1, now=at(8, 59))

    def test_online_cutoff_but_walk_in_still_allowed(self):  # R4
        with self.assertRaisesMessage(ValidationError, "closed at 12:30 PM"):
            self.take(1, now=at(12, 30))
        t = q.issue_ticket(issued_by=self.nurse, patient=self.patient(1), source="WALKIN", now=at(12, 59))
        self.assertEqual(t.status, "CHECKED_IN")

    def test_needs_a_doctor_on_duty(self):
        with self.assertRaisesMessage(ValidationError, "No doctor is on duty"):
            self.take(1, now=at(18))

    def test_who_can_issue(self):
        self.patient(1), self.patient(2)
        with self.assertRaises(PermissionDenied):
            q.issue_ticket(issued_by=self.users[1], patient=self.patients[2], source="ONLINE", now=at(9))
        with self.assertRaises(PermissionDenied):
            q.issue_ticket(issued_by=self.users[1], patient=self.patients[1], source="WALKIN", now=at(9))


class CallingTests(QueueTestCase):
    def test_calls_smallest_position_then_earlier_check_in(self):  # R5, R6, R11
        t1, t2, t3 = self.take(1), self.take(2), self.take(3)
        self.check_in(t3, at(9, 10))
        self.check_in(t2, at(9, 11))
        # same position: the earlier check-in goes first
        QueueTicket.objects.filter(pk=t2.pk).update(position=3)
        self.assertEqual(q.call_next(called_by=self.nurse, now=at(9, 20)).queue_no, 3)

    def test_only_checked_in_patients_are_called(self):  # R5
        self.take(1)
        with self.assertRaisesMessage(ValidationError, "No checked-in patients"):
            q.call_next(called_by=self.nurse, now=at(9, 20))

    def test_one_patient_called_at_a_time(self):  # R12
        for n in (1, 2):
            self.check_in(self.take(n))
        q.call_next(called_by=self.nurse, now=at(9, 20))
        with self.assertRaisesMessage(ValidationError, "has been called"):
            q.call_next(called_by=self.nurse, now=at(9, 21))

    def test_patients_cannot_run_the_queue(self):
        self.check_in(self.take(1))
        with self.assertRaises(PermissionDenied):
            q.call_next(called_by=self.users[1], now=at(9, 20))

    def test_start_and_complete(self):
        t = self.check_in(self.take(1))
        q.call_next(called_by=self.nurse, now=at(9, 20))
        q.start_consultation(started_by=self.doctor_user, ticket_id=t.pk, now=at(9, 21))
        t = q.complete_ticket(completed_by=self.doctor_user, ticket_id=t.pk, now=at(9, 30))
        self.assertEqual(t.status, "COMPLETED")
        with self.assertRaises(ValidationError):
            q.complete_ticket(completed_by=self.doctor_user, ticket_id=t.pk, now=at(9, 31))


class GraceRuleTests(QueueTestCase):
    def test_desc_example(self):  # R7: [6, 8, 10, 12, 13] -> [6, 8, 10, 2, 12, 13] -> [6, 8, 10, 2, 1, 12, 13]
        tickets = {n: self.take(n) for n in range(1, 14)}
        for n in (6, 8, 10, 12, 13):
            self.check_in(tickets[n], at(9, 10, n))
        # 1 and 2 were skipped earlier (a bigger number was called before they arrived)
        QueueTicket.objects.filter(queue_no__in=(1, 2)).update(status="SKIPPED")

        self.check_in(tickets[2], at(9, 30))
        self.assertEqual(self.line(), [6, 8, 10, 2, 12, 13])
        self.check_in(tickets[1], at(9, 31))
        self.assertEqual(self.line(), [6, 8, 10, 2, 1, 12, 13])

    def test_calling_a_bigger_number_skips_those_not_arrived(self):  # R7
        t1, t2, t3 = self.take(1), self.take(2), self.take(3)
        self.check_in(t3)
        q.call_next(called_by=self.nurse, now=at(9, 20))
        t1.refresh_from_db(), t2.refresh_from_db()
        self.assertEqual((t1.status, t2.status), ("SKIPPED", "SKIPPED"))

    def test_fewer_than_three_waiting_goes_to_the_end(self):
        t1, t2, t3 = self.take(1), self.take(2), self.take(3)
        self.check_in(t2), self.check_in(t3)
        QueueTicket.objects.filter(pk=t1.pk).update(status="SKIPPED")
        self.check_in(t1, at(9, 30))
        self.assertEqual(self.line(), [2, 3, 1])
        t1.refresh_from_db()
        self.assertEqual(t1.position, Decimal("4"))

    def test_late_at_end_of_line_still_counts_as_moved(self):
        # 4 is skipped; line [1, 2, 3] -> end of line would be position 4 = its own number
        tickets = {n: self.take(n) for n in range(1, 5)}
        for n in (1, 2, 3):
            self.check_in(tickets[n], at(9, 10, n))
        QueueTicket.objects.filter(pk=tickets[4].pk).update(status="SKIPPED")
        t4 = self.check_in(tickets[4], at(9, 30))
        self.assertEqual(self.line(), [1, 2, 3, 4])
        self.assertNotEqual(t4.position, Decimal(4))
        self.assertTrue(q.board_tickets(DAY, "MORNING")[3].is_late)


class MissedRuleTests(QueueTestCase):
    def test_no_show_rejoin_once_then_cancel(self):  # R8
        t = self.check_in(self.take(1))
        self.check_in(self.take(2))
        q.call_next(called_by=self.nurse, now=at(9, 20))
        t = q.mark_no_show(marked_by=self.nurse, ticket_id=t.pk, now=at(9, 22))
        self.assertEqual((t.status, t.miss_count), ("MISSED", 1))

        t = self.check_in(t, at(9, 25))  # rejoin, goes behind the people waiting
        self.assertTrue(t.rejoined)
        self.assertEqual(self.line(), [2, 1])

        self.serve(at(9, 30))
        q.call_next(called_by=self.nurse, now=at(9, 40))
        t = q.mark_no_show(marked_by=self.nurse, ticket_id=t.pk, now=at(9, 41))
        self.assertEqual((t.status, t.miss_count), ("CANCELLED", 2))

    def test_automatic_no_show_after_three_minutes(self):  # R8
        t = self.check_in(self.take(1))
        q.call_next(called_by=self.nurse, now=at(9, 20))
        self.assertEqual(q.run_housekeeping(now=at(9, 22, 59))["missed"], 0)
        self.assertEqual(q.run_housekeeping(now=at(9, 23))["missed"], 1)
        t.refresh_from_db()
        self.assertEqual(t.status, "MISSED")


class ExpiryAndCancelTests(QueueTestCase):
    def test_unfinished_tickets_expire_at_session_end(self):  # R9
        waiting, done = self.take(1), self.check_in(self.take(2))
        self.serve(at(9, 20))
        self.assertEqual(q.run_housekeeping(now=at(12, 59))["expired"], 0)
        self.assertEqual(q.run_housekeeping(now=at(13))["expired"], 1)
        waiting.refresh_from_db(), done.refresh_from_db()
        self.assertEqual((waiting.status, done.status), ("EXPIRED", "COMPLETED"))
        with self.assertRaisesMessage(ValidationError, "expired"):
            self.check_in(waiting, at(13, 5))

    def test_patient_cancels_own_ticket_only(self):
        t1, t2 = self.take(1), self.take(2)
        with self.assertRaises(PermissionDenied):
            q.cancel_ticket(cancelled_by=self.users[1], ticket_id=t2.pk, now=at(9, 5))
        t1 = q.cancel_ticket(cancelled_by=self.users[1], ticket_id=t1.pk, now=at(9, 5))
        self.assertEqual(t1.status, "CANCELLED")
        with self.assertRaisesMessage(ValidationError, "cancelled"):
            self.check_in(t1)
        # cancelled tickets don't block a new number (R3 counts open tickets only)
        self.assertEqual(self.take(1, now=at(9, 6)).queue_no, 3)


class LiveStatusTests(QueueTestCase):
    def test_ahead_place_wait_and_come_now(self):
        tickets = [self.check_in(self.take(n), at(9, 10, n)) for n in range(1, 7)]
        mine = tickets[4]  # number 5
        s = q.live_status(mine, now=at(9, 15))
        self.assertEqual((s["ahead"], s["place"]), (4, 5))
        self.assertEqual((s["wait_min"], s["wait_max"]), (40, 50))  # default 10 min each
        self.assertFalse(s["come_now"])

        self.serve(at(9, 20))  # takes 8 minutes -> average becomes 8
        s = q.live_status(mine, now=at(9, 30))
        self.assertEqual(s["ahead"], 3)
        self.assertTrue(s["come_now"])  # 3 or fewer ahead
        self.assertEqual(s["avg_consult_min"], 8)

    def test_pushed_back_when_a_late_patient_rejoins_ahead(self):
        late = self.take(1)
        tickets = [self.check_in(self.take(n), at(9, 10, n)) for n in range(2, 8)]
        mine = tickets[-1]  # number 7, 5 ahead
        self.assertFalse(q.live_status(mine)["pushed_back"])
        QueueTicket.objects.filter(pk=late.pk).update(status="SKIPPED")
        self.check_in(late, at(9, 30))  # goes after 2, 3, 4 -> ahead of me
        mine.refresh_from_db()
        s = q.live_status(mine)
        self.assertEqual(s["ahead"], 6)
        self.assertTrue(s["pushed_back"])

    def test_checked_in_without_check_in_time(self):
        # e.g. a ticket set to CHECKED_IN by hand in the admin
        a = self.check_in(self.take(1))
        b = self.take(2)
        QueueTicket.objects.filter(pk=b.pk).update(status="CHECKED_IN")
        b.refresh_from_db()
        self.assertEqual(q.people_ahead(b), 1)
        self.assertEqual(q.people_ahead(a), 0)

    def test_todays_ticket_includes_missed(self):
        t = self.check_in(self.take(1))
        q.call_next(called_by=self.nurse, now=at(9, 20))
        q.mark_no_show(marked_by=self.nurse, ticket_id=t.pk, now=at(9, 21))
        found = q.get_todays_ticket(self.patients[1], now=at(9, 22))
        self.assertEqual((found.pk, found.status), (t.pk, "MISSED"))
        self.assertIsNone(q.people_ahead(found))
