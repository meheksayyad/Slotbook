import secrets

from django.conf import settings
from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import DateTimeRangeField, RangeBoundary, RangeOperators
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models
from django.db.models import Func, Q

from apps.common.models import TimeStampedModel
from apps.venues.models import Court

_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I


def generate_reference() -> str:
    return "SB-" + "".join(secrets.choice(_ALPHABET) for _ in range(8))


class TsTzRange(Func):
    function = "TSTZRANGE"
    output_field = DateTimeRangeField()


class BookingQuerySet(models.QuerySet):
    def active(self):
        """Bookings that currently hold the slot."""
        return self.filter(status__in=Booking.ACTIVE_STATUSES)


class Booking(TimeStampedModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending payment"
        CONFIRMED = "confirmed", "Confirmed"
        CANCELLED = "cancelled", "Cancelled"
        EXPIRED = "expired", "Expired"
        COMPLETED = "completed", "Completed"

    ACTIVE_STATUSES = (Status.PENDING, Status.CONFIRMED)

    reference = models.CharField(max_length=16, unique=True, default=generate_reference, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="bookings")
    court = models.ForeignKey(Court, on_delete=models.PROTECT, related_name="bookings")
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING, db_index=True)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2)
    refund_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    price_breakdown = models.JSONField(default=dict, encoder=DjangoJSONEncoder)
    expires_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancellation_reason = models.CharField(max_length=255, blank=True)
    reminder_sent_at = models.DateTimeField(null=True, blank=True)

    objects = BookingQuerySet.as_manager()

    class Meta:
        ordering = ["-start_time"]
        indexes = [
            models.Index(fields=["court", "start_time"], name="booking_court_start_idx"),
            models.Index(fields=["user", "-start_time"], name="booking_user_start_idx"),
            models.Index(fields=["status", "expires_at"], name="booking_status_expiry_idx"),
        ]
        constraints = [
            models.CheckConstraint(condition=Q(end_time__gt=models.F("start_time")), name="booking_end_after_start"),
            # The database-level guarantee against double booking: no two ACTIVE bookings for the
            # same court may have overlapping [start, end) ranges - even under concurrent writers.
            ExclusionConstraint(
                name="booking_no_overlap_per_court",
                expressions=[
                    (TsTzRange("start_time", "end_time", RangeBoundary()), RangeOperators.OVERLAPS),
                    ("court", RangeOperators.EQUAL),
                ],
                condition=Q(status__in=["pending", "confirmed"]),
            ),
        ]

    def __str__(self):
        return f"{self.reference} ({self.status})"
