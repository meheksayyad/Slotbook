from celery import shared_task

from . import services


@shared_task
def retry_failed_refunds():
    return services.retry_failed_refunds()
