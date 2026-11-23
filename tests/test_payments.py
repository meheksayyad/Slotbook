import json
from datetime import timedelta

import pytest
from django.core import mail
from django.utils import timezone

from apps.payments.gateways import MockGateway, to_minor_units
from apps.payments.models import Payment, Refund

from .conftest import slot_start
from .factories import make_booking

pytestmark = pytest.mark.django_db
WEBHOOK = "/api/v1/payments/webhook/"


def send_event(client, payment, event="payment.captured", amount=None, signature=None):
    entity = {"id": "pay_123", "order_id": payment.provider_order_id, "amount": amount if amount is not None else to_minor_units(payment.amount)}
    raw = json.dumps({"event": event, "payload": {"payment": {"entity": entity}}}).encode()
    sig = signature if signature is not None else MockGateway().sign(raw)
    return client.generic("POST", WEBHOOK, raw, content_type="application/json", HTTP_X_WEBHOOK_SIGNATURE=sig)


@pytest.fixture
def pending(customer, court, venue):
    return make_booking(customer, court, slot_start(venue, 18), status="pending", expires_at=timezone.now() + timedelta(minutes=10))


def test_pay_creates_order_and_is_idempotent(client_for, customer, pending):
    c = client_for(customer)
    a = c.post(f"/api/v1/bookings/{pending.pk}/pay/")
    b = c.post(f"/api/v1/bookings/{pending.pk}/pay/")
    assert a.status_code == 201 and a.data["provider_order_id"] == b.data["provider_order_id"]
    assert Payment.objects.count() == 1


def test_only_booking_owner_can_pay(client_for, other_customer, owner, pending):
    assert client_for(other_customer).post(f"/api/v1/bookings/{pending.pk}/pay/").status_code == 404
    assert client_for(owner).post(f"/api/v1/bookings/{pending.pk}/pay/").status_code == 403


def test_cannot_pay_after_hold_expired(client_for, customer, pending):
    pending.expires_at = timezone.now() - timedelta(minutes=1)
    pending.save()
    assert client_for(customer).post(f"/api/v1/bookings/{pending.pk}/pay/").status_code == 409


def test_captured_webhook_confirms_booking_and_emails(client_for, customer, pending, django_capture_on_commit_callbacks):
    pay = client_for(customer).post(f"/api/v1/bookings/{pending.pk}/pay/").data
    payment = Payment.objects.get(pk=pay["id"])
    with django_capture_on_commit_callbacks(execute=True):
        r = send_event(client_for(), payment)
    assert r.status_code == 200 and r.data["status"] == "confirmed"
    pending.refresh_from_db(); payment.refresh_from_db()
    assert pending.status == "confirmed" and pending.expires_at is None
    assert payment.status == "succeeded" and payment.paid_at is not None
    assert len(mail.outbox) == 1 and pending.reference in mail.outbox[0].subject


def test_webhook_replay_is_idempotent(client_for, customer, pending, django_capture_on_commit_callbacks):
    payment = Payment.objects.get(pk=client_for(customer).post(f"/api/v1/bookings/{pending.pk}/pay/").data["id"])
    with django_capture_on_commit_callbacks(execute=True):
        send_event(client_for(), payment)
        again = send_event(client_for(), payment)
    assert again.data["status"] == "duplicate"
    assert len(mail.outbox) == 1


def test_invalid_signature_rejected(client_for, customer, pending):
    payment = Payment.objects.get(pk=client_for(customer).post(f"/api/v1/bookings/{pending.pk}/pay/").data["id"])
    r = send_event(client_for(), payment, signature="deadbeef")
    assert r.status_code == 400
    pending.refresh_from_db()
    assert pending.status == "pending"


def test_amount_mismatch_does_not_confirm(client_for, customer, pending):
    payment = Payment.objects.get(pk=client_for(customer).post(f"/api/v1/bookings/{pending.pk}/pay/").data["id"])
    r = send_event(client_for(), payment, amount=100)
    assert r.data["status"] == "amount_mismatch"
    pending.refresh_from_db(); payment.refresh_from_db()
    assert pending.status == "pending" and payment.status == "failed"


def test_payment_arriving_after_expiry_is_auto_refunded(client_for, customer, pending):
    payment = Payment.objects.get(pk=client_for(customer).post(f"/api/v1/bookings/{pending.pk}/pay/").data["id"])
    pending.status = "expired"
    pending.save()
    r = send_event(client_for(), payment)
    assert r.data["status"] == "refunded_inactive_booking"
    payment.refresh_from_db()
    assert payment.status == "refunded" and payment.refunded_amount == payment.amount
    assert Refund.objects.get(payment=payment).status == "processed"


def test_failed_event_keeps_order_retryable(client_for, customer, pending):
    payment = Payment.objects.get(pk=client_for(customer).post(f"/api/v1/bookings/{pending.pk}/pay/").data["id"])
    send_event(client_for(), payment, event="payment.failed")
    payment.refresh_from_db()
    assert payment.status == "created" and payment.failure_reason
