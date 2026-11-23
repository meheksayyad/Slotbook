import logging
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from . import notifications, services
from .models import Booking

logger = logging.getLogger(__name__)


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_backoff_max=600, max_retries=5)
def send_booking_notification(self, booking_id, kind):
    booking = Booking.objects.select_related("user", "court__venue").get(pk=booking_id)
    notifications.SENDERS[kind](booking)


@shared_task
def expire_pending_bookings():
    n = services.expire_stale_bookings()
    if n:
        logger.info("Expired %s unpaid bookings", n)
    return n


@shared_task
def send_booking_reminders():
    """Email confirmed bookings starting within REMINDER_LEAD_HOURS. Idempotent via reminder_sent_at."""
    now = timezone.now()
    sent = 0
    with transaction.atomic():
        due = (
            Booking.objects.select_for_update(skip_locked=True, of=("self",))
            .select_related("user", "court__venue")
            .filter(
                status=Booking.Status.CONFIRMED,
                reminder_sent_at__isnull=True,
                start_time__gt=now,
                start_time__lte=now + timedelta(hours=settings.REMINDER_LEAD_HOURS),
            )
        )
        for b in due:
            try:
                notifications.send_reminder(b)
            except Exception:  # noqa: BLE001 - retried on next beat tick
                logger.exception("Reminder failed for %s", b.reference)
                continue
            b.reminder_sent_at = now
            b.save(update_fields=["reminder_sent_at", "updated_at"])
            sent += 1
    return sent


@shared_task
def complete_finished_bookings():
    return Booking.objects.filter(status=Booking.Status.CONFIRMED, end_time__lt=timezone.now()).update(
        status=Booking.Status.COMPLETED, updated_at=timezone.now()
    )
