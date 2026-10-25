import logging

from celery import shared_task
from django.utils import timezone

from appointments.models import Appointment
from appointments.services import mark_no_show
from notifications.services import notify_admins

logger = logging.getLogger(__name__)


@shared_task
def mark_no_shows() -> int:
    missed = list(
        Appointment.objects.filter(
            status=Appointment.Status.BOOKED,
            doctor_slot__end__lt=timezone.now(),
        )
    )

    if not missed:
        notify_admins("No missed appointments today!")
        return 0

    marked = 0
    for appointment in missed:
        try:
            mark_no_show(appointment)
        except Exception:
            logger.exception("Failed to mark appointment %s as no-show", appointment.pk)
        else:
            marked += 1

    return marked
