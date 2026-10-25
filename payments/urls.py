from django.urls import include, path
from rest_framework.routers import DefaultRouter

from payments.views import PaymentViewSet, RenewPaymentView, StripeCancelView, StripeSuccessView

app_name = "payments"

router = DefaultRouter()

router.register("payments", PaymentViewSet, basename="payment")

urlpatterns = [
    path("success/", StripeSuccessView.as_view(), name="success"),
    path("cancel/", StripeCancelView.as_view(), name="cancel"),
    path("payments/<int:pk>/renew/", RenewPaymentView.as_view(), name="payment-renew"),
    path("", include(router.urls)),
]
