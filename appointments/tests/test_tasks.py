from datetime import timedelta
from unittest.mock import patch

from django.test import override_settings
from django.utils import timezone

from appointments.models import Appointment
from appointments.tasks import mark_no_shows
from core.tests.base import BaseTestCase
from doctor_slots.models import DoctorSlot


@override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
@patch("notifications.tasks.send_telegram_message")
class MarkNoShowsTaskTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        # real mark_no_show creates a NO_SHOW_FEE payment via Stripe: never call it in tests
        patcher = patch("payments.services.PaymentService.create_payment_for_appointment")
        self.mock_payment = patcher.start()
        self.addCleanup(patcher.stop)

    def _make_past_appointment(self, hours_ago=1, **kwargs):
        end = timezone.now() - timedelta(hours=hours_ago)
        slot = DoctorSlot.objects.create(
            doctor=self.doctor,
            start=end - timedelta(minutes=30),
            end=end,
        )
        return Appointment.objects.create(
            doctor_slot=slot,
            patient=self.user,
            price=self.doctor.price_per_visit,
            **kwargs,
        )

    def test_marks_past_booked_as_no_show(self, mock_send):
        past = self._make_past_appointment()

        result = mark_no_shows()

        past.refresh_from_db()
        self.assertEqual(past.status, Appointment.Status.NO_SHOW)
        self.assertEqual(result, 1)
        self.mock_payment.assert_called_once()
        mock_send.assert_called_once()

    def test_future_appointment_untouched(self, mock_send):
        mark_no_shows()

        self.appointment.refresh_from_db()
        self.assertEqual(self.appointment.status, Appointment.Status.BOOKED)

    def test_only_booked_are_affected(self, mock_send):
        done = self._make_past_appointment(status=Appointment.Status.COMPLETED)

        mark_no_shows()

        done.refresh_from_db()
        self.assertEqual(done.status, Appointment.Status.COMPLETED)

    def test_sends_message_when_nothing_missed(self, mock_send):
        result = mark_no_shows()

        self.assertEqual(result, 0)
        mock_send.assert_called_once_with("No missed appointments today!")

    @patch("appointments.tasks.mark_no_show", side_effect=[RuntimeError("stripe"), None])
    def test_continues_after_error(self, mock_mark, mock_send):
        self._make_past_appointment(hours_ago=1)
        self._make_past_appointment(hours_ago=3)

        with self.assertLogs("appointments.tasks", level="ERROR"):
            result = mark_no_shows()

        self.assertEqual(mock_mark.call_count, 2)
        self.assertEqual(result, 1)
