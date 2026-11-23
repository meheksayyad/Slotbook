from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.bookings import services
from apps.common.exceptions import InvalidBookingState
from apps.payments.models import Payment

from .factories import make_booking, make_payment

pytestmark = pytest.mark.django_db


def confirmed(customer, court, hours_ahead):
    b = make_booking(customer, court, timezone.now() + timedelta(hours=hours_ahead), status="confirmed")
    return b, make_payment(b)


@pytest.mark.parametrize("hours_ahead,expected", [(48, "1000.00"), (24.5, "1000.00"), (10, "500.00"), (2, "0.00")])
def test_customer_refund_tiers(customer, court, hours_ahead, expected):
    b, p = confirmed(customer, court, hours_ahead)
    services.cancel_booking(booking_id=b.pk, actor=customer, reason="plans changed")
    b.refresh_from_db(); p.refresh_from_db()
    assert b.status == "cancelled" and b.refund_amount == Decimal(expected)
    assert p.refunded_amount == Decimal(expected)
    expected_status = {"1000.00": "refunded", "500.00": "partially_refunded", "0.00": "succeeded"}[expected]
    assert p.status == expected_status


def test_venue_owner_cancellation_is_always_full_refund(owner, customer, court):
    b, p = confirmed(customer, court, 2)
    services.cancel_booking(booking_id=b.pk, actor=owner, reason="maintenance")
    b.refresh_from_db()
    assert b.refund_amount == Decimal("1000.00")


def test_cancel_pending_booking_has_no_refund(customer, court, venue):
    b = make_booking(customer, court, timezone.now() + timedelta(hours=30), status="pending")
    services.cancel_booking(booking_id=b.pk, actor=customer)
    b.refresh_from_db()
    assert b.status == "cancelled" and b.refund_amount == 0 and Payment.objects.count() == 0


def test_cannot_cancel_twice_or_after_start(customer, court):
    b, _ = confirmed(customer, court, 48)
    services.cancel_booking(booking_id=b.pk, actor=customer)
    with pytest.raises(InvalidBookingState):
        services.cancel_booking(booking_id=b.pk, actor=customer)
    started = make_booking(customer, court, timezone.now() - timedelta(minutes=10), status="confirmed")
    with pytest.raises(InvalidBookingState):
        services.cancel_booking(booking_id=started.pk, actor=customer)


def test_stranger_cannot_cancel(other_customer, customer, court):
    b, _ = confirmed(customer, court, 48)
    from rest_framework.exceptions import PermissionDenied
    with pytest.raises(PermissionDenied):
        services.cancel_booking(booking_id=b.pk, actor=other_customer)


def test_gateway_outage_queues_refund_instead_of_failing_cancel(customer, court, monkeypatch):
    from apps.common.exceptions import GatewayError
    from apps.payments import services as pay
    from apps.payments.gateways import MockGateway
    from apps.payments.models import Refund

    def boom(self, **kw):
        raise GatewayError("down")

    b, p = confirmed(customer, court, 48)
    monkeypatch.setattr(MockGateway, "refund", boom)
    services.cancel_booking(booking_id=b.pk, actor=customer)
    assert Refund.objects.get().status == "failed"
    monkeypatch.undo()
    assert pay.retry_failed_refunds() == 1
    p.refresh_from_db()
    assert p.status == "refunded"
