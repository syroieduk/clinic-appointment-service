from celery import shared_task

from payments.services import PaymentService


@shared_task
def expire_stale_payment_sessions() -> int:
    return PaymentService.expire_stale_sessions()
