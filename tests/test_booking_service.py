import threading
from datetime import timedelta

import pytest
from django.db import IntegrityError, connection, transaction
from django.utils import timezone

from apps.bookings import services
from apps.bookings.models import Booking
from apps.common.exceptions import InvalidBookingRequest, SlotUnavailable

from .conftest import slot_start
from .factories import make_booking

HOUR = timedelta(hours=1)
pytestmark = pytest.mark.django_db


def book(user, court, start, hours=1):
    return services.create_booking(user=user, court=court, start_time=start, end_time=start + hours * HOUR)


def test_create_booking_is_pending_with_hold(court, venue, customer):
    b = book(customer, court, slot_start(venue, 18))
    assert b.status == "pending" and b.total_amount == 1000
    assert b.reference.startswith("SB-") and b.expires_at > timezone.now()


def test_overlapping_booking_rejected_but_back_to_back_allowed(court, venue, customer, other_customer):
    s = slot_start(venue, 18)
    book(customer, court, s, hours=2)
    with pytest.raises(SlotUnavailable):
        book(other_customer, court, s + HOUR)
    book(other_customer, court, s + 2 * HOUR)  # [20,21) right after [18,20)


@pytest.mark.parametrize(
    "hour,hours,msg",
    [(5, 1, "opening hours"), (22, 2, "multiple days"), (10, 5, "Maximum booking length")],
)
def test_invalid_windows(court, venue, customer, hour, hours, msg):
    with pytest.raises(InvalidBookingRequest, match=msg):
        book(customer, court, slot_start(venue, hour), hours=hours)


def test_unaligned_start_rejected(court, venue, customer):
    s = slot_start(venue, 18) + timedelta(minutes=30)
    with pytest.raises(InvalidBookingRequest, match="slots"):
        book(customer, court, s)


def test_booking_in_the_past_or_too_soon_rejected(court, venue, customer):
    with pytest.raises(InvalidBookingRequest, match="at least"):
        book(customer, court, slot_start(venue, 12, min_days=-1))


def test_cancelled_booking_frees_slot(court, venue, customer, other_customer):
    s = slot_start(venue, 18)
    b = book(customer, court, s)
    services.cancel_booking(booking_id=b.pk, actor=customer)
    book(other_customer, court, s)


def test_database_constraint_blocks_overlap_even_if_service_bypassed(court, venue, customer):
    s = slot_start(venue, 18)
    make_booking(customer, court, s, status="confirmed")
    with pytest.raises(IntegrityError), transaction.atomic():
        make_booking(customer, court, s + timedelta(minutes=30), status="pending")


def test_database_constraint_ignores_inactive_bookings(court, venue, customer):
    s = slot_start(venue, 18)
    make_booking(customer, court, s, status="cancelled")
    make_booking(customer, court, s, status="confirmed")
    assert Booking.objects.count() == 2


@pytest.mark.django_db(transaction=True)
def test_concurrent_requests_exactly_one_wins(court, venue, customer):
    start, n, results = slot_start(venue, 20), 8, []
    barrier = threading.Barrier(n)

    def attempt():
        try:
            barrier.wait()
            book(customer, court, start)
            results.append("ok")
        except SlotUnavailable:
            results.append("conflict")
        except Exception as exc:  # noqa: BLE001
            results.append(repr(exc))
        finally:
            connection.close()

    threads = [threading.Thread(target=attempt) for _ in range(n)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert results.count("ok") == 1, results
    assert results.count("conflict") == n - 1, results
    assert Booking.objects.active().count() == 1
