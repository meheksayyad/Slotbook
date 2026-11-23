from rest_framework import serializers

from apps.venues.models import Court

from .models import Booking


class BookingSerializer(serializers.ModelSerializer):
    court_name = serializers.CharField(source="court.name", read_only=True)
    venue_id = serializers.IntegerField(source="court.venue_id", read_only=True)
    venue_name = serializers.CharField(source="court.venue.name", read_only=True)

    class Meta:
        model = Booking
        fields = [
            "id", "reference", "status", "court", "court_name", "venue_id", "venue_name",
            "start_time", "end_time", "total_amount", "refund_amount", "price_breakdown",
            "expires_at", "cancelled_at", "cancellation_reason", "created_at",
        ]
        read_only_fields = fields


class BookingCreateSerializer(serializers.Serializer):
    court = serializers.PrimaryKeyRelatedField(
        queryset=Court.objects.select_related("venue").filter(is_active=True, venue__is_active=True)
    )
    start_time = serializers.DateTimeField()
    end_time = serializers.DateTimeField()


class CancelSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, max_length=255, default="")
