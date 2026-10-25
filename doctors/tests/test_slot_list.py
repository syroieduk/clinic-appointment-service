from datetime import datetime, time, timedelta
from decimal import Decimal

from django.urls import reverse
from django.utils import timezone
from rest_framework import status

from appointments.models import Appointment
from core.tests.base import BaseTestCase
from doctor_slots.models import DoctorSlot
from doctors.models import Doctor


def doctor_slots_url(doctor_id):
    return reverse("doctors:doctor-slots", args=[doctor_id])


class DoctorSlotListTests(BaseTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        # A week ahead: later than BaseTestCase's slot (tomorrow), never in the past
        cls.workday = timezone.localdate() + timedelta(days=7)

        cls.slot_9 = cls.make_slot(cls.doctor, 9, 0)
        cls.slot_10 = cls.make_slot(cls.doctor, 10, 0)
        cls.slot_11 = cls.make_slot(cls.doctor, 11, 0)

        cls.other_doctor = Doctor.objects.create(
            first_name="Petro",
            last_name="Shevchenko",
            price_per_visit=Decimal("500.00"),
        )
        cls.other_doctor_slot = cls.make_slot(cls.other_doctor, 9, 0)

    @classmethod
    def aware(cls, hour, minute=0):
        return timezone.make_aware(datetime.combine(cls.workday, time(hour, minute)))

    @classmethod
    def make_slot(cls, doctor, hour, minute, length=30):
        start = cls.aware(hour, minute)
        return DoctorSlot.objects.create(doctor=doctor, start=start, end=start + timedelta(minutes=length))

    def get_ids(self, **params):
        res = self.client.get(doctor_slots_url(self.doctor.id), params)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        return [slot["id"] for slot in res.data]

    def local_iso(self, hour, minute=0):
        # Naive ISO string, as a client would type it: interpreted in project TIME_ZONE
        return datetime.combine(self.workday, time(hour, minute)).isoformat(timespec="minutes")

    # --- no filters ---

    def test_returns_only_this_doctors_slots_ordered_by_start(self):
        ids = self.get_ids()

        self.assertEqual(ids, [self.slot.id, self.slot_9.id, self.slot_10.id, self.slot_11.id])
        self.assertNotIn(self.other_doctor_slot.id, ids)

    def test_anonymous_can_list_slots(self):
        res = self.client.get(doctor_slots_url(self.doctor.id))

        self.assertEqual(res.status_code, status.HTTP_200_OK)

    def test_unknown_doctor_returns_404(self):
        res = self.client.get(doctor_slots_url(999999))

        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    # --- from / to ---

    def test_from_keeps_slots_starting_at_or_after(self):
        ids = self.get_ids(**{"from": self.local_iso(10, 0)})

        self.assertEqual(set(ids), {self.slot_10.id, self.slot_11.id})

    def test_to_keeps_slots_ending_at_or_before(self):
        ids = self.get_ids(to=self.local_iso(10, 30))

        self.assertEqual(set(ids), {self.slot.id, self.slot_9.id, self.slot_10.id})

    def test_to_excludes_slot_crossing_the_boundary(self):
        # 10:00-10:30 does not fit into "until 10:15"
        ids = self.get_ids(to=self.local_iso(10, 15))

        self.assertNotIn(self.slot_10.id, ids)
        self.assertIn(self.slot_9.id, ids)

    def test_from_and_to_together(self):
        ids = self.get_ids(**{"from": self.local_iso(9, 30), "to": self.local_iso(11, 0)})

        self.assertEqual(ids, [self.slot_10.id])

    def test_datetime_with_offset_is_accepted(self):
        ids = self.get_ids(**{"from": self.aware(10, 0).isoformat()})

        self.assertEqual(set(ids), {self.slot_10.id, self.slot_11.id})

    def test_invalid_from_returns_400(self):
        res = self.client.get(doctor_slots_url(self.doctor.id), {"from": "abc"})

        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("from", res.data)

    def test_impossible_date_returns_400(self):
        res = self.client.get(doctor_slots_url(self.doctor.id), {"to": "2026-13-01T09:00"})

        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("to", res.data)

    # --- available_only ---

    def test_available_only_excludes_booked_slots(self):
        # self.slot from BaseTestCase has a BOOKED appointment
        ids = self.get_ids(available_only="true")

        self.assertNotIn(self.slot.id, ids)
        self.assertEqual(set(ids), {self.slot_9.id, self.slot_10.id, self.slot_11.id})

    def test_available_only_keeps_slot_with_cancelled_appointment(self):
        Appointment.objects.create(
            doctor_slot=self.slot_10,
            patient=self.user,
            price=self.doctor.price_per_visit,
            status=Appointment.Status.CANCELLED,
        )

        ids = self.get_ids(available_only="true")

        self.assertIn(self.slot_10.id, ids)

    def test_available_only_false_returns_all(self):
        ids = self.get_ids(available_only="false")

        self.assertIn(self.slot.id, ids)
        self.assertEqual(len(ids), 4)

    def test_available_only_is_case_insensitive(self):
        ids = self.get_ids(available_only="True")

        self.assertNotIn(self.slot.id, ids)

    def test_filters_combine(self):
        Appointment.objects.create(
            doctor_slot=self.slot_10,
            patient=self.user,
            price=self.doctor.price_per_visit,
        )

        ids = self.get_ids(**{"from": self.local_iso(9, 0), "available_only": "true"})

        self.assertEqual(set(ids), {self.slot_9.id, self.slot_11.id})
