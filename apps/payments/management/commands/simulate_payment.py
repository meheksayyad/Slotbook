import json

from django.core.management.base import BaseCommand, CommandError

from apps.payments import services
from apps.payments.gateways import MockGateway, to_minor_units
from apps.payments.models import Payment


class Command(BaseCommand):
    help = "Dev helper: simulate the (mock) gateway calling our webhook for an order."

    def add_arguments(self, parser):
        parser.add_argument("order_id")
        parser.add_argument("--fail", action="store_true", help="Simulate a failed payment instead.")

    def handle(self, *args, order_id, fail, **opts):
        try:
            p = Payment.objects.get(provider_order_id=order_id)
        except Payment.DoesNotExist:
            raise CommandError("Unknown order id")
        entity = {"id": f"pay_mock_{order_id[-8:]}", "order_id": order_id, "amount": to_minor_units(p.amount)}
        event = {"event": "payment.failed" if fail else "payment.captured", "payload": {"payment": {"entity": entity}}}
        raw = json.dumps(event).encode()
        result = services.handle_webhook(raw, MockGateway().sign(raw))
        self.stdout.write(self.style.SUCCESS(f"Webhook processed: {result}"))
