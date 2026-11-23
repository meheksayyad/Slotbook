from datetime import timedelta

import pytest
from django.core import mail
from django.utils import timezone

from apps.bookings import tasks
from apps.bookings.models import Booking

from .conftest import slot_start
from .factories import make_booking

pytestmark = pytest.mark.django_db


def test_expire_releases_only_stale_pending(customer, court, venue):
    now = timezone.now()
    stale = make_booking(customer, court, slot_start(venue, 10), status="pending", expires_at=now - timedelta(minutes=1))
    fresh = make_booking(customer, court, slot_start(venue, 12), status="pending", expires_at=now + timedelta(minutes=5))
    paid = make_booking(customer, court, slot_start(venue, 14), status="confirmed")
    assert tasks.expire_pending_bookings() == 1
    for b in (stale, fresh, paid):
        b.refresh_from_db()
    assert (stale.status, fresh.status, paid.status) == ("expired", "pending", "confirmed")


def test_reminders_sent_once_inside_window(customer, court, venue):
    soon = make_booking(customer, court, timezone.now() + timedelta(hours=1), status="confirmed")
    later = make_booking(customer, court, timezone.now() + timedelta(hours=5), status="confirmed")
    unpaid = make_booking(customer, court, timezone.now() + timedelta(hours=1, minutes=1) + timedelta(days=1), status="pending")
    assert tasks.send_booking_reminders() == 1
    assert tasks.send_booking_reminders() == 0  # idempotent
    assert len(mail.outbox) == 1 and customer.email in mail.outbox[0].to
    soon.refresh_from_db(); later.refresh_from_db()
    assert soon.reminder_sent_at is not None and later.reminder_sent_at is None


def test_complete_finished_bookings(customer, court):
    done = make_booking(customer, court, timezone.now() - timedelta(hours=3), status="confirmed")
    upcoming = make_booking(customer, court, timezone.now() + timedelta(hours=3), status="confirmed")
    assert tasks.complete_finished_bookings() == 1
    done.refresh_from_db(); upcoming.refresh_from_db()
    assert done.status == Booking.Status.COMPLETED and upcoming.status == "confirmed"
