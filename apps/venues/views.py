from django.db.models import Q
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import SAFE_METHODS
from rest_framework.response import Response

from apps.accounts.permissions import IsVenueManager, IsVenueManagerOrReadOnly
from apps.bookings import services as booking_services

from .models import Court, PricingRule, Venue
from .serializers import (
    AvailabilityQuerySerializer, CourtSerializer, PricingRuleSerializer, QuoteQuerySerializer, VenueSerializer,
)
from . import pricing


def _is_admin(user):
    return getattr(user, "is_admin_role", False)


class VenueViewSet(viewsets.ModelViewSet):
    """Public read of active venues; owners manage only their own venues."""

    serializer_class = VenueSerializer
    permission_classes = [IsVenueManagerOrReadOnly]
    filterset_fields = ["city"]
    search_fields = ["name", "city", "address"]
    ordering_fields = ["name", "created_at"]

    def get_queryset(self):
        qs = Venue.objects.prefetch_related("courts")
        user = self.request.user
        if self.request.method in SAFE_METHODS:
            if _is_admin(user):
                return qs
            flt = Q(is_active=True)
            if user.is_authenticated:
                flt |= Q(owner=user)
            return qs.filter(flt)
        return qs if _is_admin(user) else qs.filter(owner=user)

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)


class CourtViewSet(viewsets.ModelViewSet):
    serializer_class = CourtSerializer
    permission_classes = [IsVenueManagerOrReadOnly]
    filterset_fields = ["venue", "sport", "venue__city"]
    search_fields = ["name", "venue__name"]
    ordering_fields = ["base_price_per_hour", "name"]

    def get_queryset(self):
        qs = Court.objects.select_related("venue")
        user = self.request.user
        if self.request.method in SAFE_METHODS:
            if _is_admin(user):
                return qs
            flt = Q(is_active=True, venue__is_active=True)
            if user.is_authenticated:
                flt |= Q(venue__owner=user)
            return qs.filter(flt)
        return qs if _is_admin(user) else qs.filter(venue__owner=user)

    @action(detail=True, methods=["get"])
    def availability(self, request, pk=None):
        """Real-time slot grid for a court on a given date (cached ~30s, invalidated on every booking change)."""
        court = self.get_object()
        q = AvailabilityQuerySerializer(data=request.query_params)
        q.is_valid(raise_exception=True)
        return Response(booking_services.get_availability(court, q.validated_data["date"]))

    @action(detail=True, methods=["get"])
    def quote(self, request, pk=None):
        """Price a window without creating a booking."""
        court = self.get_object()
        q = QuoteQuerySerializer(data=request.query_params)
        q.is_valid(raise_exception=True)
        start, end = q.validated_data["start_time"], q.validated_data["end_time"]
        booking_services.validate_window(court, start, end)
        return Response(pricing.quote(court, start, end))


class PricingRuleViewSet(viewsets.ModelViewSet):
    serializer_class = PricingRuleSerializer
    permission_classes = [IsVenueManager]
    filterset_fields = ["venue", "court", "day_type", "is_active"]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return PricingRule.objects.none()
        qs = PricingRule.objects.select_related("venue", "court")
        user = self.request.user
        return qs if _is_admin(user) else qs.filter(venue__owner=user)
