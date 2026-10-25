from datetime import timedelta

from django.urls import reverse
from django.utils import timezone
from rest_framework import status

from appointments.models import Appointment
from core.tests.base import BaseTestCase
from doctor_slots.models import DoctorSlot


def slot_detail_url(slot_id):
    return reverse("doctor_slots:slot-detail", args=[slot_id])


class SlotDetailTests(BaseTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        start = timezone.now().replace(second=0, microsecond=0) + timedelta(days=7)
        cls.free_slot = DoctorSlot.objects.create(doctor=cls.doctor, start=start, end=start + timedelta(minutes=30))

    # --- retrieve ---

    def test_anonymous_can_retrieve_slot(self):
        res = self.client.get(slot_detail_url(self.free_slot.id))

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["id"], self.free_slot.id)
        self.assertEqual(res.data["doctor"], self.doctor.id)
        self.assertEqual(set(res.data), {"id", "doctor", "start", "end"})

    def test_unknown_slot_returns_404(self):
        res = self.client.get(slot_detail_url(999999))

        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    # --- destroy ---

    def test_admin_can_delete_free_slot(self):
        res = self.admin_client.delete(slot_detail_url(self.free_slot.id))

        self.assertEqual(res.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(DoctorSlot.objects.filter(pk=self.free_slot.id).exists())

    def test_cannot_delete_slot_with_booked_appointment(self):
        # self.slot from BaseTestCase has a BOOKED appointment
        res = self.admin_client.delete(slot_detail_url(self.slot.id))

        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertTrue(DoctorSlot.objects.filter(pk=self.slot.id).exists())
        self.assertTrue(Appointment.objects.filter(pk=self.appointment.id).exists())

    def test_cannot_delete_slot_with_cancelled_appointment(self):
        Appointment.objects.create(
            doctor_slot=self.free_slot,
            patient=self.user,
            price=self.doctor.price_per_visit,
            status=Appointment.Status.CANCELLED,
        )

        res = self.admin_client.delete(slot_detail_url(self.free_slot.id))

        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertTrue(DoctorSlot.objects.filter(pk=self.free_slot.id).exists())

    def test_patient_cannot_delete_slot(self):
        res = self.auth_client.delete(slot_detail_url(self.free_slot.id))

        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(DoctorSlot.objects.filter(pk=self.free_slot.id).exists())

    def test_anonymous_cannot_delete_slot(self):
        res = self.client.delete(slot_detail_url(self.free_slot.id))

        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_update_is_not_allowed(self):
        res = self.admin_client.patch(slot_detail_url(self.free_slot.id), {"end": "2030-01-01T10:00"}, format="json")

        self.assertEqual(res.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
