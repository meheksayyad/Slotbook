"""Payment gateway adapters. Business code only talks to the PaymentGateway interface.

* MockGateway     - deterministic, offline; used for dev/tests and demos.
* RazorpayGateway - real REST integration (Orders + Refunds + signed webhooks); needs API keys.
Webhook payloads follow Razorpay's event shape for both, so one handler serves both.
"""
import hashlib
import hmac
import uuid
from abc import ABC, abstractmethod
from decimal import Decimal

import requests
from django.conf import settings

from apps.common.exceptions import GatewayError


def to_minor_units(amount: Decimal) -> int:
    return int((Decimal(amount) * 100).to_integral_value())


class PaymentGateway(ABC):
    name: str
    signature_header: str

    @abstractmethod
    def create_order(self, *, amount: Decimal, currency: str, receipt: str) -> dict: ...

    @abstractmethod
    def verify_webhook(self, raw_body: bytes, signature: str) -> bool: ...

    @abstractmethod
    def refund(self, *, payment_id: str, amount: Decimal, reason: str) -> dict: ...

    def public_config(self) -> dict:
        return {}


class MockGateway(PaymentGateway):
    name = "mock"
    signature_header = "X-Webhook-Signature"

    def sign(self, raw_body: bytes) -> str:
        return hmac.new(settings.PAYMENT_WEBHOOK_SECRET.encode(), raw_body, hashlib.sha256).hexdigest()

    def create_order(self, *, amount, currency, receipt):
        return {"id": f"order_mock_{uuid.uuid4().hex[:16]}"}

    def verify_webhook(self, raw_body, signature):
        return hmac.compare_digest(self.sign(raw_body), signature or "")

    def refund(self, *, payment_id, amount, reason):
        return {"id": f"rfnd_mock_{uuid.uuid4().hex[:16]}", "status": "processed"}


class RazorpayGateway(PaymentGateway):
    name = "razorpay"
    signature_header = "X-Razorpay-Signature"
    base_url = "https://api.razorpay.com/v1"

    def _post(self, path, payload):
        try:
            r = requests.post(
                f"{self.base_url}{path}",
                json=payload,
                auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET),
                timeout=10,
            )
            r.raise_for_status()
            return r.json()
        except requests.RequestException as exc:
            raise GatewayError(str(exc)) from exc

    def create_order(self, *, amount, currency, receipt):
        data = self._post("/orders", {"amount": to_minor_units(amount), "currency": currency, "receipt": receipt})
        return {"id": data["id"]}

    def verify_webhook(self, raw_body, signature):
        expected = hmac.new(settings.PAYMENT_WEBHOOK_SECRET.encode(), raw_body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature or "")

    def refund(self, *, payment_id, amount, reason):
        data = self._post(f"/payments/{payment_id}/refund", {"amount": to_minor_units(amount), "notes": {"reason": reason}})
        return {"id": data["id"], "status": data.get("status", "processed")}

    def public_config(self):
        return {"key_id": settings.RAZORPAY_KEY_ID}


_REGISTRY = {"mock": MockGateway, "razorpay": RazorpayGateway}


def get_gateway(name=None) -> PaymentGateway:
    return _REGISTRY[name or settings.PAYMENT_GATEWAY]()
