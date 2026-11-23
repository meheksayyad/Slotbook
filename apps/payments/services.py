import json
import logging
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from apps.bookings import services as booking_services
from apps.bookings.models import Booking
from apps.common.exceptions import GatewayError, InvalidBookingState, PaymentError

from .gateways import get_gateway
from .models import Payment, Refund

logger = logging.getLogger(__name__)
PAID = (Payment.Status.SUCCEEDED, Payment.Status.PARTIALLY_REFUNDED)


class InvalidSignature(Exception):
    pass


@transaction.atomic
def initiate_payment(*, booking_id, user):
    """Idempotent: returns the open payment order if one already exists for this booking."""
    booking = Booking.objects.select_for_update(of=("self",)).get(pk=booking_id)
    if booking.user_id != user.id:
        raise PermissionDenied("Only the booking owner can pay for it.")
    if booking.status != Booking.Status.PENDING:
        raise InvalidBookingState(f"A {booking.status} booking cannot be paid.")
    if booking.expires_at and booking.expires_at < timezone.now():
        raise InvalidBookingState("This booking's payment window has expired.")

    existing = booking.payments.filter(status=Payment.Status.CREATED).first()
    if existing:
        return existing
    gw = get_gateway()
    try:
        order = gw.create_order(amount=booking.total_amount, currency=settings.PAYMENT_CURRENCY, receipt=booking.reference)
    except GatewayError as exc:
        logger.exception("Gateway order creation failed for %s", booking.reference)
        raise PaymentError("Payment provider is unavailable, please retry.") from exc
    return Payment.objects.create(
        booking=booking, provider=gw.name, provider_order_id=order["id"],
        amount=booking.total_amount, currency=settings.PAYMENT_CURRENCY,
    )


def handle_webhook(raw_body: bytes, signature: str) -> str:
    """Verify + dispatch a gateway event. Idempotent: replays are acknowledged and ignored."""
    gw = get_gateway()
    if not gw.verify_webhook(raw_body, signature):
        raise InvalidSignature()
    try:
        event = json.loads(raw_body)
        etype = event["event"]
        entity = event["payload"]["payment"]["entity"]
    except (ValueError, KeyError, TypeError):
        return "ignored"
    if etype == "payment.captured":
        return _on_captured(entity)
    if etype == "payment.failed":
        return _on_failed(entity)
    return "ignored"


@transaction.atomic
def _on_captured(entity) -> str:
    payment = Payment.objects.select_for_update().filter(provider_order_id=entity.get("order_id")).first()
    if payment is None:
        logger.warning("Webhook for unknown order %s", entity.get("order_id"))
        return "unknown_order"
    if payment.status != Payment.Status.CREATED:
        return "duplicate"  # idempotent replay

    paid = Decimal(entity["amount"]) / 100
    if paid != payment.amount:
        payment.status, payment.failure_reason = Payment.Status.FAILED, f"Amount mismatch: got {paid}"
        payment.raw_event = entity
        payment.save()
        logger.error("Amount mismatch on %s: expected %s got %s", payment.provider_order_id, payment.amount, paid)
        return "amount_mismatch"

    payment.status, payment.paid_at = Payment.Status.SUCCEEDED, timezone.now()
    payment.provider_payment_id, payment.raw_event = entity["id"], entity
    payment.save()

    booking = Booking.objects.select_for_update(of=("self",)).select_related("court__venue").get(pk=payment.booking_id)
    if booking.status == Booking.Status.PENDING:
        booking_services.confirm_booking(booking)
        return "confirmed"
    # Money arrived for a booking that expired/was cancelled meanwhile -> give it back in full.
    refund_payment(payment, payment.amount, "Booking no longer active")
    return "refunded_inactive_booking"


@transaction.atomic
def _on_failed(entity) -> str:
    payment = Payment.objects.select_for_update().filter(provider_order_id=entity.get("order_id")).first()
    if payment is None or payment.status != Payment.Status.CREATED:
        return "ignored"
    payment.failure_reason = str(entity.get("error_description", "Payment failed"))[:255]
    payment.save(update_fields=["failure_reason", "updated_at"])  # stays CREATED so the user can retry
    return "failed_recorded"


def refund_for_booking(booking, amount, reason):
    payment = booking.payments.select_for_update().filter(status__in=PAID).order_by("-paid_at").first()
    return refund_payment(payment, amount, reason) if payment else None


def refund_payment(payment, amount, reason):
    """Refund via the gateway. A gateway outage records a FAILED refund (retried by Celery) rather than
    failing the cancellation that triggered it."""
    amount = min(Decimal(amount), payment.amount - payment.refunded_amount)
    if amount <= 0:
        return None
    try:
        res = get_gateway(payment.provider).refund(payment_id=payment.provider_payment_id, amount=amount, reason=reason)
    except GatewayError:
        logger.exception("Refund failed for %s; queued for retry", payment.provider_order_id)
        return Refund.objects.create(payment=payment, amount=amount, status=Refund.Status.FAILED, reason=reason)
    refund = Refund.objects.create(
        payment=payment, amount=amount, status=Refund.Status.PROCESSED, provider_refund_id=res["id"], reason=reason
    )
    _apply_refund(payment, amount)
    return refund


def _apply_refund(payment, amount):
    payment.refunded_amount += amount
    payment.status = Payment.Status.REFUNDED if payment.refunded_amount >= payment.amount else Payment.Status.PARTIALLY_REFUNDED
    payment.save(update_fields=["refunded_amount", "status", "updated_at"])


def retry_failed_refunds(limit=50) -> int:
    done = 0
    with transaction.atomic():
        pending = list(
            Refund.objects.select_for_update(skip_locked=True, of=("self",))
            .select_related("payment").filter(status=Refund.Status.FAILED)[:limit]
        )
        for r in pending:
            try:
                res = get_gateway(r.payment.provider).refund(
                    payment_id=r.payment.provider_payment_id, amount=r.amount, reason=r.reason
                )
            except GatewayError:
                continue
            r.status, r.provider_refund_id = Refund.Status.PROCESSED, res["id"]
            r.save(update_fields=["status", "provider_refund_id", "updated_at"])
            _apply_refund(r.payment, r.amount)
            done += 1
    return done
