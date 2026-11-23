from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from apps.bookings.models import Booking
from apps.payments.models import Payment


def make_booking(user, court, start, hours=1, status="confirmed", amount="1000.00", **kw):
    return Booking.objects.create(
        user=user, court=court, start_time=start, end_time=start + timedelta(hours=hours),
        status=status, total_amount=Decimal(amount), **kw,
    )


def make_payment(booking, status="succeeded", order="order_t1", pay_id="pay_t1"):
    return Payment.objects.create(
        booking=booking, provider="mock", provider_order_id=order, provider_payment_id=pay_id,
        amount=booking.total_amount, status=status, paid_at=timezone.now() if status == "succeeded" else None,
    )
