from datetime import timedelta

from django.utils import timezone

from appointments.models import Appointment
from notifications.messages import (
    appointment_cancelled,
    appointment_completed,
    appointment_no_show,
)
from notifications.services import notify_admins
from payments.models import Payment
from payments.services import PaymentService


def cancel_appointment(appointment, request=None):
    if appointment.status != Appointment.Status.BOOKED:
        raise ValueError("Only booked appointments can be cancelled.")

    time_until_appointment = appointment.doctor_slot.start - timezone.now()

    if time_until_appointment < timedelta(hours=24):
        PaymentService.create_payment_for_appointment(
            appointment,
            Payment.Type.CANCELLATION_FEE,
            request,
        )

    appointment.status = Appointment.Status.CANCELLED
    appointment.save(update_fields=["status"])

    notify_admins(appointment_cancelled(appointment))

    return appointment


def complete_appointment(appointment, request=None):
    if appointment.status != Appointment.Status.BOOKED:
        raise ValueError("Only booked appointments can be completed.")

    PaymentService.create_payment_for_appointment(
        appointment,
        Payment.Type.CONSULTATION,
        request,
    )

    appointment.status = Appointment.Status.COMPLETED
    appointment.completed_at = timezone.now()
    appointment.save(update_fields=["status", "completed_at"])

    notify_admins(appointment_completed(appointment))

    return appointment


def mark_no_show(appointment, request=None):
    if appointment.status != Appointment.Status.BOOKED:
        raise ValueError("Only booked appointments can be marked as no-show.")

    PaymentService.create_payment_for_appointment(
        appointment,
        Payment.Type.NO_SHOW_FEE,
        request,
    )

    appointment.status = Appointment.Status.NO_SHOW
    appointment.save(update_fields=["status"])

    notify_admins(appointment_no_show(appointment))

    return appointment
