from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from rest_framework import serializers

from .models import Court, PricingRule, Venue


class CourtSerializer(serializers.ModelSerializer):
    class Meta:
        model = Court
        fields = ["id", "venue", "name", "sport", "base_price_per_hour", "is_active"]

    def validate_venue(self, venue):
        user = self.context["request"].user
        if not user.is_admin_role and venue.owner_id != user.id:
            raise serializers.ValidationError("You can only manage courts of your own venues.")
        return venue


class VenueSerializer(serializers.ModelSerializer):
    courts = CourtSerializer(many=True, read_only=True)
    owner = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = Venue
        fields = [
            "id", "owner", "name", "slug", "description", "address", "city", "timezone",
            "opening_time", "closing_time", "slot_minutes", "is_active", "courts",
        ]
        read_only_fields = ["slug"]

    def validate_timezone(self, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise serializers.ValidationError("Unknown IANA timezone.")
        return value

    def validate(self, attrs):
        opening = attrs.get("opening_time", getattr(self.instance, "opening_time", None))
        closing = attrs.get("closing_time", getattr(self.instance, "closing_time", None))
        if opening and closing and opening >= closing:
            raise serializers.ValidationError("opening_time must be earlier than closing_time (single-day operation).")
        return attrs


class PricingRuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = PricingRule
        fields = ["id", "venue", "court", "name", "day_type", "start_time", "end_time", "multiplier", "priority", "is_active"]

    def validate(self, attrs):
        g = lambda k: attrs.get(k, getattr(self.instance, k, None))  # noqa: E731
        venue, court = g("venue"), g("court")
        user = self.context["request"].user
        if not user.is_admin_role and venue.owner_id != user.id:
            raise serializers.ValidationError("You can only manage rules of your own venues.")
        if court and court.venue_id != venue.id:
            raise serializers.ValidationError("Court does not belong to the given venue.")
        if g("start_time") >= g("end_time"):
            raise serializers.ValidationError("start_time must be earlier than end_time.")
        return attrs


class AvailabilityQuerySerializer(serializers.Serializer):
    date = serializers.DateField()


class QuoteQuerySerializer(serializers.Serializer):
    start_time = serializers.DateTimeField()
    end_time = serializers.DateTimeField()
