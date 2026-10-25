from decimal import ROUND_HALF_UP, Decimal

import stripe
from django.conf import settings
from django.db import transaction
from django.http import HttpRequest
from django.urls import NoReverseMatch, reverse

from payments.models import Payment

stripe.api_key = settings.STRIPE_SECRET_KEY


class PaymentService:
    RATE_COEFFICIENTS = {
        Payment.Type.CONSULTATION: Decimal("1.0"),
        Payment.Type.CANCELLATION_FEE: Decimal("0.5"),
        Payment.Type.NO_SHOW_FEE: Decimal("1.2"),
    }

    @classmethod
    def calculate_amount(
        cls,
        base_price: Decimal | str | int,
        payment_type: str,
        rounding: str = ROUND_HALF_UP,
    ) -> Decimal:
        if not isinstance(base_price, Decimal):
            try:
                base_price = Decimal(str(base_price))
            except Exception as exc:
                raise ValueError(f"Invalid price format: {base_price}") from exc

        if base_price < Decimal("0.00"):
            raise ValueError("Price cannot be negative.")

        if payment_type not in cls.RATE_COEFFICIENTS:
            valid_types = ", ".join(cls.RATE_COEFFICIENTS.keys())
            raise ValueError(f"Unknown payment type '{payment_type}'. Valid: {valid_types}")

        coefficient = cls.RATE_COEFFICIENTS[payment_type]
        amount = base_price * coefficient

        return amount.quantize(Decimal("0.01"), rounding=rounding)

    @staticmethod
    def to_stripe_cents(amount: Decimal | str | int) -> int:
        if not isinstance(amount, Decimal):
            amount = Decimal(str(amount))

        cents = (amount * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        return int(cents)

    @classmethod
    def _get_redirect_urls(cls, request: HttpRequest | None = None) -> tuple[str, str]:
        if request is not None:
            base_url = request.build_absolute_uri("/")[:-1]
        else:
            base_url = getattr(settings, "SITE_URL", "http://localhost:8000")
            if base_url.endswith("/"):
                base_url = base_url[:-1]

        try:
            success_path = reverse("payments:success")
            cancel_path = reverse("payments:cancel")
        except NoReverseMatch:
            success_path = "/success/"
            cancel_path = "/cancel/"

        success_url = f"{base_url}{success_path}?session_id={{CHECKOUT_SESSION_ID}}"
        cancel_url = f"{base_url}{cancel_path}"
        return success_url, cancel_url

    @classmethod
    def create_payment_for_appointment(
        cls,
        appointment,
        payment_type: str,
        request: HttpRequest | None = None,
    ) -> Payment:
        existing_payment = Payment.objects.filter(
            appointment=appointment,
            type=payment_type,
            status__in=[Payment.Status.PENDING, Payment.Status.PAID],
        ).first()

        if existing_payment:
            return existing_payment

        money_to_pay = cls.calculate_amount(appointment.price, payment_type)
        stripe_cents = cls.to_stripe_cents(money_to_pay)
        success_url, cancel_url = cls._get_redirect_urls(request)

        try:
            stripe_session = stripe.checkout.Session.create(
                line_items=[
                    {
                        "price_data": {
                            "currency": "usd",
                            "product_data": {
                                "name": (f"Payment for Appointment #{appointment.id}"),
                                "description": f"Type: {payment_type}",
                            },
                            "unit_amount": stripe_cents,
                        },
                        "quantity": 1,
                    }
                ],
                mode="payment",
                success_url=success_url,
                cancel_url=cancel_url,
                metadata={
                    "appointment_id": appointment.id,
                    "payment_type": payment_type,
                },
            )
        except stripe.error.StripeError as exc:
            raise RuntimeError(f"Stripe error: {exc.user_message or str(exc)}") from exc

        with transaction.atomic():
            payment = Payment.objects.create(
                appointment=appointment,
                status=Payment.Status.PENDING,
                type=payment_type,
                session_id=stripe_session.id,
                session_url=stripe_session.url,
                money_to_pay=money_to_pay,
            )

        return payment

    @classmethod
    def renew(
        cls,
        payment: Payment,
        request: HttpRequest | None = None,
    ) -> Payment:
        success_url, cancel_url = cls._get_redirect_urls(request)
        stripe_cents = cls.to_stripe_cents(payment.money_to_pay)

        stripe_session = stripe.checkout.Session.create(
            line_items=[
                {
                    "price_data": {
                        "currency": "usd",
                        "product_data": {
                            "name": f"{payment.type} Payment",
                        },
                        "unit_amount": stripe_cents,
                    },
                    "quantity": 1,
                }
            ],
            mode="payment",
            success_url=success_url,
            cancel_url=cancel_url,
            metadata={
                "appointment_id": payment.appointment.id,
                "payment_type": payment.type,
            },
        )

        with transaction.atomic():
            payment.session_id = stripe_session.id
            payment.session_url = stripe_session.url
            payment.status = Payment.Status.PENDING
            payment.save(update_fields=["session_id", "session_url", "status"])

        return payment

    renew_payment = renew

    @classmethod
    def expire_stale_sessions(cls) -> int:
        pending = Payment.objects.filter(status=Payment.Status.PENDING)
        expired_ids = []
        for payment in pending:
            try:
                session = stripe.checkout.Session.retrieve(payment.session_id)
            except stripe.error.StripeError:
                continue
            if session.status == "expired":
                expired_ids.append(payment.pk)
        return Payment.objects.filter(pk__in=expired_ids).update(status=Payment.Status.EXPIRED)
