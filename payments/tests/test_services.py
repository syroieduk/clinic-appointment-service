from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.test import SimpleTestCase

from core.tests.base import BaseTestCase
from payments.models import Payment
from payments.services import PaymentService


# ---------- Calculation Tests ----------
class PaymentServiceCalculationTests(SimpleTestCase):
    def test_consultation_amount(self):
        """CONSULTATION: 1.0 * price."""
        price = Decimal("800.00")
        result = PaymentService.calculate_amount(price, Payment.Type.CONSULTATION)
        self.assertEqual(result, Decimal("800.00"))

    def test_cancellation_fee_amount(self):
        """CANCELLATION_FEE: 0.5 * price."""
        price = Decimal("800.00")
        result = PaymentService.calculate_amount(price, Payment.Type.CANCELLATION_FEE)
        self.assertEqual(result, Decimal("400.00"))

    def test_no_show_fee_amount(self):
        """NO_SHOW_FEE: 1.2 * price."""
        price = Decimal("800.00")
        result = PaymentService.calculate_amount(price, Payment.Type.NO_SHOW_FEE)
        self.assertEqual(result, Decimal("960.00"))

    def test_rounding_precision(self):
        price = Decimal("33.33")
        result = PaymentService.calculate_amount(price, Payment.Type.CANCELLATION_FEE)
        self.assertEqual(result, Decimal("16.67"))

    def test_accepts_str_and_int_types(self):
        self.assertEqual(
            PaymentService.calculate_amount("800.00", Payment.Type.CONSULTATION),
            Decimal("800.00"),
        )
        self.assertEqual(
            PaymentService.calculate_amount(800, Payment.Type.CONSULTATION),
            Decimal("800.00"),
        )

    def test_negative_price_raises_error(self):
        with self.assertRaises(ValueError):
            PaymentService.calculate_amount(Decimal("-100.00"), Payment.Type.CONSULTATION)

    def test_to_stripe_cents(self):
        self.assertEqual(PaymentService.to_stripe_cents(Decimal("10.00")), 1000)
        self.assertEqual(PaymentService.to_stripe_cents(Decimal("0.99")), 99)


# ---------- Stripe API ----------
class PaymentServiceStripeTests(BaseTestCase):
    @patch("stripe.checkout.Session.create")
    def test_create_payment_success(self, mock_stripe_create):
        mock_stripe_create.return_value = MagicMock(
            id="sess_test_123",
            url="https://checkout.stripe.com/pay/sess_test_123",
        )

        payment = PaymentService.create_payment_for_appointment(
            appointment=self.appointment,
            payment_type=Payment.Type.CONSULTATION,
        )

        self.assertEqual(payment.session_id, "sess_test_123")
        self.assertEqual(payment.money_to_pay, self.appointment.price)
        mock_stripe_create.assert_called_once()

        call_kwargs = mock_stripe_create.call_args.kwargs
        line_item = call_kwargs["line_items"][0]
        self.assertEqual(line_item["price_data"]["unit_amount"], 80000)

        site_url = settings.SITE_URL.rstrip("/")
        self.assertTrue(call_kwargs["success_url"].startswith(site_url))
        self.assertIn("?session_id={CHECKOUT_SESSION_ID}", call_kwargs["success_url"])
        self.assertTrue(call_kwargs["cancel_url"].startswith(site_url))

    @patch("stripe.checkout.Session.create")
    def test_returns_existing_payment_without_calling_stripe(self, mock_stripe_create):
        existing_payment = Payment.objects.create(
            appointment=self.appointment,
            type=Payment.Type.CONSULTATION,
            status=Payment.Status.PENDING,
            session_id="sess_existing",
            session_url="https://checkout.stripe.com/existing",
            money_to_pay=self.appointment.price,
        )

        payment = PaymentService.create_payment_for_appointment(
            appointment=self.appointment,
            payment_type=Payment.Type.CONSULTATION,
        )

        self.assertEqual(payment.id, existing_payment.id)
        mock_stripe_create.assert_not_called()

    @patch("stripe.checkout.Session.create")
    def test_renew_payment_success(self, mock_stripe_create):
        mock_stripe_create.return_value = MagicMock(
            id="sess_renewed_456",
            url="https://checkout.stripe.com/pay/sess_renewed_456",
        )
        expired_payment = Payment.objects.create(
            appointment=self.appointment,
            type=Payment.Type.CONSULTATION,
            status=Payment.Status.EXPIRED,
            session_id="sess_old_123",
            session_url="https://checkout.stripe.com/old",
            money_to_pay=self.appointment.price,
        )

        renewed = PaymentService.renew(expired_payment)

        self.assertEqual(renewed.id, expired_payment.id)
        self.assertEqual(renewed.status, Payment.Status.PENDING)
        self.assertEqual(renewed.session_id, "sess_renewed_456")
        self.assertEqual(renewed.session_url, "https://checkout.stripe.com/pay/sess_renewed_456")
        mock_stripe_create.assert_called_once()
        call_kwargs = mock_stripe_create.call_args.kwargs
        self.assertEqual(
            call_kwargs["metadata"],
            {
                "appointment_id": self.appointment.id,
                "payment_type": Payment.Type.CONSULTATION,
            },
        )
