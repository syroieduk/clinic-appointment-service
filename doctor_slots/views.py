from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_view
from rest_framework.exceptions import ValidationError
from rest_framework.mixins import DestroyModelMixin, RetrieveModelMixin
from rest_framework.viewsets import GenericViewSet

from core.permissions import IsAdminOrReadOnly
from doctor_slots.models import DoctorSlot
from doctor_slots.serializers import DoctorSlotSerializer


@extend_schema(tags=["Slots"])
@extend_schema_view(
    retrieve=extend_schema(
        summary="Retrieve a slot",
        description="Available to everyone, including anonymous users.",
        responses={
            200: DoctorSlotSerializer,
            404: OpenApiResponse(description="Slot not found."),
        },
    ),
    destroy=extend_schema(
        summary="Delete a slot",
        description="Admin only. A slot that has any appointment, including a cancelled one, cannot be deleted.",
        responses={
            204: None,
            400: OpenApiResponse(description="Slot has appointments."),
            404: OpenApiResponse(description="Slot not found."),
        },
    ),
)
class DoctorSlotsViewSet(RetrieveModelMixin, DestroyModelMixin, GenericViewSet):
    queryset = DoctorSlot.objects.all()
    serializer_class = DoctorSlotSerializer
    permission_classes = (IsAdminOrReadOnly,)

    def perform_destroy(self, instance):
        if instance.appointments.exists():
            raise ValidationError("Cannot delete a slot that has appointments. Cancel or move them first.")
        instance.delete()
