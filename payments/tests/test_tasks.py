from unittest.mock import MagicMock, patch

from core.tests.base import BaseTestCase
from payments.models import Payment
from payments.services import PaymentService
from payments.tasks import expire_stale_payment_sessions


class ExpireStaleSessionsServiceTests(BaseTestCase):
    @patch("stripe.checkout.Session.retrieve")
    def test_marks_expired_session_as_expired(self, mock_retrieve):
        payment = Payment.objects.create(
            appointment=self.appointment,
            type=Payment.Type.CONSULTATION,
            status=Payment.Status.PENDING,
            session_id="sess_expired_111",
            session_url="https://checkout.stripe.com/expired_111",
            money_to_pay=self.appointment.price,
        )
        mock_retrieve.return_value = MagicMock(status="expired")

        count = PaymentService.expire_stale_sessions()

        payment.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.EXPIRED)
        self.assertEqual(count, 1)

    @patch("stripe.checkout.Session.retrieve")
    def test_ignores_open_session(self, mock_retrieve):
        payment = Payment.objects.create(
            appointment=self.appointment,
            type=Payment.Type.CONSULTATION,
            status=Payment.Status.PENDING,
            session_id="sess_open_222",
            session_url="https://checkout.stripe.com/open_222",
            money_to_pay=self.appointment.price,
        )
        mock_retrieve.return_value = MagicMock(status="open")

        count = PaymentService.expire_stale_sessions()

        payment.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.PENDING)
        self.assertEqual(count, 0)

    @patch("stripe.checkout.Session.retrieve")
    def test_ignores_complete_session(self, mock_retrieve):
        payment = Payment.objects.create(
            appointment=self.appointment,
            type=Payment.Type.CONSULTATION,
            status=Payment.Status.PENDING,
            session_id="sess_complete_333",
            session_url="https://checkout.stripe.com/complete_333",
            money_to_pay=self.appointment.price,
        )
        mock_retrieve.return_value = MagicMock(status="complete")

        count = PaymentService.expire_stale_sessions()

        payment.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.PENDING)
        self.assertEqual(count, 0)

    @patch("stripe.checkout.Session.retrieve")
    def test_skips_payment_on_stripe_error(self, mock_retrieve):
        import stripe as stripe_module

        payment = Payment.objects.create(
            appointment=self.appointment,
            type=Payment.Type.CONSULTATION,
            status=Payment.Status.PENDING,
            session_id="sess_error_444",
            session_url="https://checkout.stripe.com/error_444",
            money_to_pay=self.appointment.price,
        )
        mock_retrieve.side_effect = stripe_module.error.StripeError("network error")

        count = PaymentService.expire_stale_sessions()

        payment.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.PENDING)
        self.assertEqual(count, 0)

    @patch("stripe.checkout.Session.retrieve")
    def test_does_not_touch_already_paid(self, mock_retrieve):
        Payment.objects.create(
            appointment=self.appointment,
            type=Payment.Type.CONSULTATION,
            status=Payment.Status.PAID,
            session_id="sess_paid_555",
            session_url="https://checkout.stripe.com/paid_555",
            money_to_pay=self.appointment.price,
        )
        mock_retrieve.return_value = MagicMock(status="expired")

        PaymentService.expire_stale_sessions()

        mock_retrieve.assert_not_called()


class ExpireStaleSessionsTaskTests(BaseTestCase):
    @patch("payments.services.PaymentService.expire_stale_sessions")
    def test_task_delegates_to_service(self, mock_service):
        mock_service.return_value = 3

        result = expire_stale_payment_sessions()

        mock_service.assert_called_once()
        self.assertEqual(result, 3)
