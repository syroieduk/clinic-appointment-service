import stripe
from django.shortcuts import get_object_or_404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema, extend_schema_view
from rest_framework import status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core import settings
from payments.models import Payment
from payments.serializers import PaymentSerializer
from payments.services import PaymentService

stripe.api_key = settings.STRIPE_SECRET_KEY


@extend_schema(tags=["Payments"])
@extend_schema_view(
    list=extend_schema(
        summary="List payments",
        description="Authenticated users see their own payments. Admins see all payments.",
        responses={
            200: PaymentSerializer(many=True),
        },
    ),
    retrieve=extend_schema(
        summary="Retrieve payment details",
        description="Get full payment information including session details.",
        responses={
            200: PaymentSerializer,
            404: OpenApiResponse(description="Payment not found."),
        },
    ),
)
class PaymentViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = PaymentSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Payment.objects.none()
        user = self.request.user
        if user.is_staff:
            return Payment.objects.all()
        return Payment.objects.filter(appointment__patient=user)


@extend_schema(
    tags=["Payments"],
    summary="Stripe payment success callback",
    description=(
        "Called by Stripe after successful payment. Verifies payment status with Stripe "
        "and updates the payment status to PAID if confirmed. Requires session_id query parameter."
    ),
    parameters=[
        OpenApiParameter(
            name="session_id",
            type=OpenApiTypes.STR,
            location=OpenApiParameter.QUERY,
            required=True,
            description="Stripe checkout session ID",
        ),
    ],
    responses={
        200: OpenApiResponse(description="Payment status checked successfully."),
        400: OpenApiResponse(description="Session ID missing or Stripe error."),
        404: OpenApiResponse(description="Payment not found."),
    },
)
class StripeSuccessView(APIView):
    def get(self, request):
        session_id = request.GET.get("session_id")
        if not session_id:
            return Response({"error": "Session ID required"}, status=status.HTTP_400_BAD_REQUEST)

        payment = Payment.objects.filter(session_id=session_id).first()
        if not payment:
            return Response({"error": "Payment not found"}, status=status.HTTP_404_NOT_FOUND)

        try:
            session = stripe.checkout.Session.retrieve(session_id)
            payment_status = (
                session.get("payment_status") if isinstance(session, dict) else getattr(session, "payment_status", None)
            )

            if payment_status == "paid":
                payment.status = Payment.Status.PAID
                payment.save()
                return Response({"status": Payment.Status.PAID}, status=status.HTTP_200_OK)
            return Response({"status": Payment.Status.PENDING}, status=status.HTTP_200_OK)
        except stripe.error.StripeError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)


@extend_schema(
    tags=["Payments"],
    summary="Stripe payment cancel callback",
    description="Called by Stripe when the user cancels the payment. Returns a cancellation message.",
    responses={
        200: OpenApiResponse(description="Payment was cancelled."),
    },
)
class StripeCancelView(APIView):
    def get(self, request):
        return Response({"message": "The payment was cancelled."}, status=status.HTTP_200_OK)


@extend_schema(
    tags=["Payments"],
    summary="Renew an expired payment",
    description=(
        "Creates a new Stripe checkout session for an expired payment. "
        "Only the payment owner can renew their own expired payments."
    ),
    responses={
        201: OpenApiResponse(
            description="New payment session created successfully.",
            response={
                "type": "object",
                "properties": {
                    "session_id": {"type": "string"},
                    "session_url": {"type": "string"},
                },
            },
        ),
        400: OpenApiResponse(description="Payment is not expired or Stripe error."),
        401: OpenApiResponse(description="Authentication required."),
        404: OpenApiResponse(description="Payment not found."),
    },
)
class RenewPaymentView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        payment = get_object_or_404(Payment, pk=pk)

        if payment.appointment.patient != request.user:
            return Response({"detail": "Payment not found"}, status=status.HTTP_404_NOT_FOUND)

        if payment.status != Payment.Status.EXPIRED:
            return Response({"detail": "Only EXPIRED payments can be renewed"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            renewed_payment = PaymentService.renew(payment, request=request)
            return Response(
                {
                    "session_id": renewed_payment.session_id,
                    "session_url": renewed_payment.session_url,
                },
                status=status.HTTP_201_CREATED,
            )
        except stripe.error.StripeError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
