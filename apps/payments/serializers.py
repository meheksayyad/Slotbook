from rest_framework import serializers

from .gateways import get_gateway
from .models import Payment


class PaymentSerializer(serializers.ModelSerializer):
    booking_reference = serializers.CharField(source="booking.reference", read_only=True)
    checkout = serializers.SerializerMethodField()

    class Meta:
        model = Payment
        fields = [
            "id", "booking", "booking_reference", "provider", "provider_order_id", "amount", "currency",
            "status", "refunded_amount", "paid_at", "failure_reason", "checkout", "created_at",
        ]
        read_only_fields = fields

    def get_checkout(self, obj):
        """What the client SDK needs to open the gateway's checkout."""
        return {"order_id": obj.provider_order_id, **get_gateway(obj.provider).public_config()}
