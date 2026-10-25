from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from appointments.models import Appointment
from doctor_slots.models import DoctorSlot
from doctor_slots.serializers import DoctorSlotDetailSerializer
from notifications.messages import appointment_booked
from notifications.services import notify_admins
from payments.models import Payment
from payments.serializers import PaymentSerializer


class AppointmentListSerializer(serializers.ModelSerializer):
    doctor = serializers.CharField(
        source="doctor_slot.doctor",
        read_only=True,
    )
    start = serializers.DateTimeField(
        source="doctor_slot.start",
        read_only=True,
    )
    end = serializers.DateTimeField(
        source="doctor_slot.end",
        read_only=True,
    )

    class Meta:
        model = Appointment
        fields = [
            "id",
            "patient",
            "doctor",
            "start",
            "end",
            "status",
            "price",
        ]


class AppointmentDetailSerializer(serializers.ModelSerializer):
    doctor_slot = DoctorSlotDetailSerializer(read_only=True)
    payments = PaymentSerializer(many=True, read_only=True)

    class Meta:
        model = Appointment
        fields = [
            "id",
            "patient",
            "doctor_slot",
            "status",
            "booked_at",
            "completed_at",
            "price",
            "payments",
        ]


class AppointmentCreateSerializer(serializers.ModelSerializer):
    doctor_slot = serializers.PrimaryKeyRelatedField(
        queryset=DoctorSlot.objects.all(),
    )

    class Meta:
        model = Appointment
        fields = ["id", "doctor_slot", "patient", "status", "price"]
        read_only_fields = ["id", "patient", "status", "price"]

    def validate_doctor_slot(self, doctor_slot):
        if doctor_slot.start <= timezone.now():
            raise serializers.ValidationError("The appointment slot must be in the future.")

        if Appointment.objects.filter(
            doctor_slot=doctor_slot,
            status=Appointment.Status.BOOKED,
        ).exists():
            raise serializers.ValidationError("This slot is already booked.")

        return doctor_slot

    def validate(self, attrs):
        attrs = super().validate(attrs)
        user_patient = self.context["request"].user
        unpaid_problem_here = Payment.objects.filter(
            appointment__patient=user_patient,
            status__in=[Payment.Status.PENDING, Payment.Status.EXPIRED],
        ).exists()
        if unpaid_problem_here:
            raise serializers.ValidationError(
                "You have an unpaid payment and it might become a problem for you. Please pay it or else."
            )
        return attrs

    def create(self, validated_data):
        with transaction.atomic():
            try:
                doctor_slot = (
                    DoctorSlot.objects.select_for_update()
                    .select_related("doctor")
                    .get(pk=validated_data["doctor_slot"].pk)
                )
            except DoctorSlot.DoesNotExist:
                raise serializers.ValidationError({"doctor_slot": "This slot does not exist."}) from None

            if doctor_slot.start <= timezone.now():
                raise serializers.ValidationError({"doctor_slot": "This slot is no longer in the future."})

            if Appointment.objects.filter(
                doctor_slot=doctor_slot,
                status=Appointment.Status.BOOKED,
            ).exists():
                raise serializers.ValidationError({"doctor_slot": "This slot is already booked."})

            appointment = Appointment.objects.create(
                doctor_slot=doctor_slot,
                patient=self.context["request"].user,
                price=doctor_slot.doctor.price_per_visit,
            )

            transaction.on_commit(lambda: notify_admins(appointment_booked(appointment)))

        return appointment
