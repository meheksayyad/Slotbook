from django.core.serializers.json import DjangoJSONEncoder
from django.db import models

from apps.bookings.models import Booking
from apps.common.models import TimeStampedModel


class Payment(TimeStampedModel):
    class Status(models.TextChoices):
        CREATED = "created", "Created"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"
        PARTIALLY_REFUNDED = "partially_refunded", "Partially refunded"
        REFUNDED = "refunded", "Refunded"

    booking = models.ForeignKey(Booking, on_delete=models.PROTECT, related_name="payments")
    provider = models.CharField(max_length=20)
    provider_order_id = models.CharField(max_length=64, unique=True)
    provider_payment_id = models.CharField(max_length=64, blank=True, db_index=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default="INR")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.CREATED, db_index=True)
    refunded_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    paid_at = models.DateTimeField(null=True, blank=True, db_index=True)
    failure_reason = models.CharField(max_length=255, blank=True)
    raw_event = models.JSONField(default=dict, blank=True, encoder=DjangoJSONEncoder)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(condition=models.Q(refunded_amount__lte=models.F("amount")), name="payment_refund_le_amount"),
        ]

    def __str__(self):
        return f"{self.provider_order_id} ({self.status})"


class Refund(TimeStampedModel):
    class Status(models.TextChoices):
        PROCESSED = "processed", "Processed"
        FAILED = "failed", "Failed (will retry)"

    payment = models.ForeignKey(Payment, on_delete=models.PROTECT, related_name="refunds")
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=12, choices=Status.choices, db_index=True)
    provider_refund_id = models.CharField(max_length=64, blank=True)
    reason = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-created_at"]
