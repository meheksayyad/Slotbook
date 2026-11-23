"""Booking domain logic. Views stay thin; everything transactional lives here.

Double-booking defence in depth:
  1. Per-court row lock (SELECT ... FOR UPDATE) serialises concurrent writers on the same court.
  2. Explicit overlap query gives a clean 409 in the common case.
  3. PostgreSQL EXCLUDE constraint is the final, unbypassable guarantee (raises IntegrityError -> 409).
"""
import logging
from datetime import datetime, timedelta

from django.conf import settings
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from apps.common.exceptions import InvalidBookingRequest, InvalidBookingState, SlotUnavailable
from apps.venues import pricing
from apps.venues.models import Court

from .models import Booking

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------ helpers
def enqueue_notification(booking_id, kind):
    def _send():
        from .tasks import send_booking_notification

        try:
            send_booking_notification.delay(booking_id, kind)
        except Exception:  # noqa: BLE001 - broker outage must never fail the request
            logger.exception("Could not enqueue %s notification for booking %s", kind, booking_id)

    transaction.on_commit(_send)


def _availability_key(court_id, day):
    return f"availability:{court_id}:{day.isoformat()}"


def invalidate_availability(court, start, end):
    tz, day = court.venue.tz, start.astimezone(court.venue.tz).date()
    last = (end - timedelta(seconds=1)).astimezone(tz).date()
    while day <= last:
        cache.delete(_availability_key(court.pk, day))
        day += timedelta(days=1)


def validate_window(court, start, end, *, now=None):
    now = now or timezone.now()
    venue = court.venue
    if not (court.is_active and venue.is_active):
        raise InvalidBookingRequest("This court is not open for booking.")
    if end <= start:
        raise InvalidBookingRequest("end_time must be after start_time.")
    ls, le = start.astimezone(venue.tz), end.astimezone(venue.tz)
    if ls.date() != le.date():
        raise InvalidBookingRequest("A booking cannot span multiple days.")
    open_dt, close_dt = pricing.day_window(venue, ls.date())
    if ls < open_dt or le > close_dt:
        raise InvalidBookingRequest(
            f"Outside opening hours ({venue.opening_time:%H:%M}-{venue.closing_time:%H:%M} {venue.timezone})."
        )
    slot = venue.slot_minutes
    offset = (ls - open_dt).total_seconds() / 60
    duration = (end - start).total_seconds() / 60
    if offset % slot or duration % slot:
        raise InvalidBookingRequest(f"Bookings must align to {slot}-minute slots from opening time.")
    if duration > settings.BOOKING_MAX_DURATION_HOURS * 60:
        raise InvalidBookingRequest(f"Maximum booking length is {settings.BOOKING_MAX_DURATION_HOURS} hours.")
    if start < now + timedelta(minutes=settings.BOOKING_MIN_LEAD_MINUTES):
        raise InvalidBookingRequest(f"Bookings must start at least {settings.BOOKING_MIN_LEAD_MINUTES} minutes from now.")
    if start > now + timedelta(days=settings.BOOKING_MAX_ADVANCE_DAYS):
        raise InvalidBookingRequest(f"Bookings open up to {settings.BOOKING_MAX_ADVANCE_DAYS} days in advance.")


# ------------------------------------------------------------- availability
def get_availability(court, day):
    key = _availability_key(court.pk, day)
    cached = cache.get(key)
    if cached is not None:
        return cached
    venue = court.venue
    open_dt, close_dt = pricing.day_window(venue, day)
    busy = list(
        Booking.objects.active()
        .filter(court=court, start_time__lt=close_dt, end_time__gt=open_dt)
        .values_list("start_time", "end_time")
    )
    util, rules, now, slots = pricing.day_utilisation(court, day), pricing.load_rules(venue), timezone.now(), []
    for s, e in pricing.iter_slots(open_dt, close_dt, venue.slot_minutes):
        taken = any(bs < e and be > s for bs, be in busy)
        p = pricing.price_slot(court, rules, s, e, util)
        slots.append(
            {
                "start": s.isoformat(),
                "end": e.isoformat(),
                "available": (not taken) and s > now,
                "price": str(p["price"]),
                "multiplier": str(p["multiplier"]),
                "surge": p["surge"],
            }
        )
    data = {
        "court": court.pk,
        "date": day.isoformat(),
        "timezone": venue.timezone,
        "utilisation": str(util),
        "slots": slots,
    }
    cache.set(key, data, settings.AVAILABILITY_CACHE_TTL)
    return data


# ----------------------------------------------------------------- commands
@transaction.atomic
def create_booking(*, user, court, start_time, end_time):
    now = timezone.now()
    validate_window(court, start_time, end_time, now=now)

    # (1) serialise writers per court
    Court.objects.select_for_update().filter(pk=court.pk).first()

    # (2) friendly conflict detection
    if Booking.objects.active().filter(court=court, start_time__lt=end_time, end_time__gt=start_time).exists():
        raise SlotUnavailable()

    quote = pricing.quote(court, start_time, end_time)
    try:
        # (3) savepoint so an IntegrityError doesn't poison the outer transaction
        with transaction.atomic():
            booking = Booking.objects.create(
                user=user,
                court=court,
                start_time=start_time,
                end_time=end_time,
                status=Booking.Status.PENDING,
                total_amount=quote["total"],
                price_breakdown=quote,
                expires_at=now + timedelta(minutes=settings.BOOKING_HOLD_MINUTES),
            )
    except IntegrityError as exc:
        raise SlotUnavailable() from exc

    transaction.on_commit(lambda: invalidate_availability(court, start_time, end_time))
    logger.info("Booking %s created (pending) for court %s", booking.reference, court.pk)
    return booking


def confirm_booking(booking):
    """Caller must hold a row lock on `booking` (see payments.services)."""
    booking.status = Booking.Status.CONFIRMED
    booking.expires_at = None
    booking.save(update_fields=["status", "expires_at", "updated_at"])
    court = booking.court
    transaction.on_commit(lambda: invalidate_availability(court, booking.start_time, booking.end_time))
    enqueue_notification(booking.pk, "confirmed")


def compute_refund(booking, *, now=None, full=False):
    """Refund amount for cancelling a CONFIRMED booking, per settings.REFUND_POLICY."""
    from apps.venues.pricing import money

    if booking.status != Booking.Status.CONFIRMED:
        return money(0)
    if full:
        return money(booking.total_amount)
    hours = (booking.start_time - (now or timezone.now())).total_seconds() / 3600
    for threshold, pct in settings.REFUND_POLICY:
        if hours >= threshold:
            return money(booking.total_amount * pct / 100)
    return money(0)


@transaction.atomic
def cancel_booking(*, booking_id, actor, reason=""):
    from apps.payments import services as payment_services

    booking = (
        Booking.objects.select_for_update(of=("self",)).select_related("court__venue").get(pk=booking_id)
    )
    is_customer = booking.user_id == actor.id
    is_manager = actor.is_admin_role or booking.court.venue.owner_id == actor.id
    if not (is_customer or is_manager):
        raise PermissionDenied("You cannot cancel this booking.")
    now = timezone.now()
    if booking.status not in Booking.ACTIVE_STATUSES:
        raise InvalidBookingState(f"A {booking.status} booking cannot be cancelled.")
    if booking.start_time <= now:
        raise InvalidBookingState("This booking has already started.")

    # Venue-initiated cancellations are always refunded in full.
    refund = compute_refund(booking, now=now, full=is_manager and not is_customer)
    was_confirmed = booking.status == Booking.Status.CONFIRMED
    booking.status = Booking.Status.CANCELLED
    booking.cancelled_at = now
    booking.cancellation_reason = reason[:255]
    booking.refund_amount = refund
    booking.expires_at = None
    booking.save()

    if was_confirmed and refund > 0:
        payment_services.refund_for_booking(booking, refund, reason or "Booking cancelled")

    court = booking.court
    transaction.on_commit(lambda: invalidate_availability(court, booking.start_time, booking.end_time))
    enqueue_notification(booking.pk, "cancelled")
    return booking


def expire_stale_bookings(batch_size=200) -> int:
    """Release slots held by unpaid bookings. Safe to run concurrently (SKIP LOCKED)."""
    now, n = timezone.now(), 0
    with transaction.atomic():
        stale = list(
            Booking.objects.select_for_update(skip_locked=True, of=("self",))
            .select_related("court__venue")
            .filter(status=Booking.Status.PENDING, expires_at__lt=now)[:batch_size]
        )
        for b in stale:
            b.status = Booking.Status.EXPIRED
            b.save(update_fields=["status", "updated_at"])
            court, s, e = b.court, b.start_time, b.end_time
            transaction.on_commit(lambda c=court, s=s, e=e: invalidate_availability(c, s, e))
            n += 1
    return n
