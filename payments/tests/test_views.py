from unittest.mock import MagicMock, patch

import stripe
from django.contrib.auth import get_user_model
from django.urls import reverse

from core.tests.base import BaseTestCase
from payments.models import Payment

User = get_user_model()


class PaymentSuccessViewTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.payment = Payment.objects.create(
            appointment=self.appointment,
            type=Payment.Type.CONSULTATION,
            status=Payment.Status.PENDING,
            session_id="sess_success_123",
            session_url="https://checkout.stripe.com/pay/sess_success_123",
            money_to_pay=self.appointment.price,
        )
        self.url = reverse("payments:success")

    @patch("stripe.checkout.Session.retrieve")
    def test_marks_payment_paid_when_stripe_confirms(self, mock_retrieve):
        mock_retrieve.return_value = MagicMock(payment_status="paid")

        response = self.client.get(self.url, {"session_id": self.payment.session_id})

        self.assertEqual(response.status_code, 200)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, Payment.Status.PAID)
        self.assertEqual(response.data["status"], Payment.Status.PAID)

    @patch("stripe.checkout.Session.retrieve")
    def test_keeps_pending_when_stripe_not_paid(self, mock_retrieve):
        mock_retrieve.return_value = MagicMock(payment_status="unpaid")

        response = self.client.get(self.url, {"session_id": self.payment.session_id})

        self.assertEqual(response.status_code, 200)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, Payment.Status.PENDING)

    def test_returns_400_without_session_id(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 400)

    def test_returns_404_for_unknown_session_id(self):
        response = self.client.get(self.url, {"session_id": "sess_unknown"})
        self.assertEqual(response.status_code, 404)

    @patch("stripe.checkout.Session.retrieve")
    def test_does_not_downgrade_already_paid(self, mock_retrieve):
        self.payment.status = Payment.Status.PAID
        self.payment.save()
        mock_retrieve.return_value = MagicMock(payment_status="unpaid")

        self.client.get(self.url, {"session_id": self.payment.session_id})

        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, Payment.Status.PAID)


class PaymentCancelViewTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.url = reverse("payments:cancel")

    def test_returns_200_with_message(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertIn("cancelled", response.data["message"].lower())


class RenewPaymentViewTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.expired_payment = Payment.objects.create(
            appointment=self.appointment,
            type=Payment.Type.CONSULTATION,
            status=Payment.Status.EXPIRED,
            session_id="sess_expired_old",
            session_url="https://checkout.stripe.com/old",
            money_to_pay=self.appointment.price,
        )
        self.url = reverse("payments:payment-renew", kwargs={"pk": self.expired_payment.pk})

    @patch("stripe.checkout.Session.create")
    def test_renew_expired_returns_201_with_new_session(self, mock_create):
        mock_create.return_value = MagicMock(
            id="sess_renewed_123",
            url="https://checkout.stripe.com/pay/sess_renewed_123",
        )

        response = self.auth_client.post(self.url)

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["session_id"], "sess_renewed_123")
        mock_create.assert_called_once()

        call_kwargs = mock_create.call_args.kwargs
        line_item = call_kwargs["line_items"][0]
        self.assertEqual(line_item["price_data"]["unit_amount"], 80000)

        success_path = reverse("payments:success")
        cancel_path = reverse("payments:cancel")
        self.assertIn(success_path, call_kwargs["success_url"])
        self.assertIn("?session_id={CHECKOUT_SESSION_ID}", call_kwargs["success_url"])
        self.assertIn(cancel_path, call_kwargs["cancel_url"])
        self.assertEqual(
            call_kwargs["metadata"],
            {
                "appointment_id": self.appointment.id,
                "payment_type": Payment.Type.CONSULTATION,
            },
        )

    def test_renew_non_expired_returns_400(self):
        pending_payment = Payment.objects.create(
            appointment=self.appointment,
            type=Payment.Type.CANCELLATION_FEE,
            status=Payment.Status.PENDING,
            session_id="sess_pending_456",
            session_url="https://checkout.stripe.com/pending",
            money_to_pay=self.appointment.price,
        )
        url = reverse("payments:payment-renew", kwargs={"pk": pending_payment.pk})

        response = self.auth_client.post(url)

        self.assertEqual(response.status_code, 400)
        self.assertIn("EXPIRED", response.data["detail"])

    def test_renew_requires_authentication(self):
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 401)

    def test_renew_returns_404_for_unknown_payment(self):
        url = reverse("payments:payment-renew", kwargs={"pk": 99999})
        response = self.auth_client.post(url)
        self.assertEqual(response.status_code, 404)

    def test_renew_other_user_payment_returns_404(self):
        other_user = User.objects.create_user(
            email="other@example.com",
            password="password123",
        )
        self.client.force_authenticate(user=other_user)
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 404)

    @patch("stripe.checkout.Session.create")
    def test_renew_stripe_error_returns_400(self, mock_create):
        mock_create.side_effect = stripe.error.StripeError("Stripe API error")

        response = self.auth_client.post(self.url)

        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.data)
