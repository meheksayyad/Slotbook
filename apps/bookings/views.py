import django_filters
from django.db.models import Q
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle, UserRateThrottle

from apps.payments import services as payment_services
from apps.payments.serializers import PaymentSerializer

from . import services
from .models import Booking
from .serializers import BookingCreateSerializer, BookingSerializer, CancelSerializer


class BookingFilter(django_filters.FilterSet):
    date_from = django_filters.DateFilter(field_name="start_time", lookup_expr="date__gte")
    date_to = django_filters.DateFilter(field_name="start_time", lookup_expr="date__lte")
    venue = django_filters.NumberFilter(field_name="court__venue_id")

    class Meta:
        model = Booking
        fields = ["status", "court"]


class BookingViewSet(mixins.CreateModelMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = BookingSerializer
    filterset_class = BookingFilter
    ordering_fields = ["start_time", "created_at", "total_amount"]
    throttle_classes = [UserRateThrottle, ScopedRateThrottle]
    throttle_scope = "booking"

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Booking.objects.none()
        qs = Booking.objects.select_related("court__venue", "user")
        u = self.request.user
        if u.is_admin_role:
            return qs
        if u.is_venue_manager:
            return qs.filter(Q(user=u) | Q(court__venue__owner=u))
        return qs.filter(user=u)

    def create(self, request, *args, **kwargs):
        s = BookingCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        booking = services.create_booking(user=request.user, **s.validated_data)
        return Response(BookingSerializer(booking).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        booking = self.get_object()
        s = CancelSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        booking = services.cancel_booking(booking_id=booking.pk, actor=request.user, reason=s.validated_data["reason"])
        return Response(BookingSerializer(booking).data)

    @action(detail=True, methods=["post"])
    def pay(self, request, pk=None):
        """Create (or return the open) payment order for a pending booking."""
        booking = self.get_object()
        payment = payment_services.initiate_payment(booking_id=booking.pk, user=request.user)
        return Response(PaymentSerializer(payment).data, status=status.HTTP_201_CREATED)
