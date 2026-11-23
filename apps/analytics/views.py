"""Read-only reporting for venue owners (own venues) and platform admins (all venues).

Revenue is cash-based: gross = successful payments by paid_at date; net = gross - refunds
(refunds are attributed to the original payment's date).
"""
from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, DecimalField, Q, Sum, Value
from django.db.models.functions import Coalesce, TruncDate
from django.utils import timezone
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsVenueManager
from apps.bookings.models import Booking
from apps.payments.models import Payment
from apps.venues.models import Venue

ZERO = Value(Decimal("0.00"), output_field=DecimalField(max_digits=12, decimal_places=2))
REVENUE_STATUSES = [Booking.Status.CONFIRMED, Booking.Status.COMPLETED]


class RangeSerializer(serializers.Serializer):
    date_from = serializers.DateField(required=False)
    date_to = serializers.DateField(required=False)
    venue = serializers.IntegerField(required=False)

    def validate(self, a):
        today = timezone.localdate()
        a.setdefault("date_to", today)
        a.setdefault("date_from", a["date_to"] - timedelta(days=29))
        if a["date_from"] > a["date_to"]:
            raise serializers.ValidationError("date_from must not be after date_to.")
        if (a["date_to"] - a["date_from"]).days > 92:
            raise serializers.ValidationError("Maximum range is 93 days.")
        return a


class BaseAnalyticsView(APIView):
    permission_classes = [IsVenueManager]

    def parse(self, request):
        s = RangeSerializer(data=request.query_params)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        venues = Venue.objects.all() if request.user.is_admin_role else Venue.objects.filter(owner=request.user)
        if "venue" in d:
            venues = venues.filter(pk=d["venue"])
        return d, venues


class SummaryView(BaseAnalyticsView):
    def get(self, request):
        d, venues = self.parse(request)
        lo, hi = d["date_from"], d["date_to"]
        pay = Payment.objects.filter(booking__court__venue__in=venues, paid_at__date__range=(lo, hi))
        money = pay.aggregate(
            gross=Coalesce(Sum("amount"), ZERO), refunded=Coalesce(Sum("refunded_amount"), ZERO), payments=Count("id")
        )
        bookings = Booking.objects.filter(court__venue__in=venues, start_time__date__range=(lo, hi))
        by_status = {s: c for s, c in bookings.values_list("status").annotate(c=Count("id"))}
        total = sum(by_status.values())
        cancelled = by_status.get(Booking.Status.CANCELLED, 0)

        booked_h = sum(
            (e - s).total_seconds() / 3600
            for s, e in bookings.filter(status__in=REVENUE_STATUSES).values_list("start_time", "end_time")
        )
        days = (hi - lo).days + 1
        available_h = 0.0
        for v in venues.annotate(n=Count("courts", filter=Q(courts__is_active=True))):
            hours = (v.closing_time.hour * 60 + v.closing_time.minute - v.opening_time.hour * 60 - v.opening_time.minute) / 60
            available_h += v.n * hours * days

        return Response(
            {
                "range": {"from": lo, "to": hi},
                "revenue": {"gross": money["gross"], "refunded": money["refunded"], "net": money["gross"] - money["refunded"]},
                "bookings": {
                    "total": total,
                    "by_status": by_status,
                    "cancellation_rate": round(cancelled / total, 4) if total else 0,
                },
                "occupancy": {
                    "booked_hours": round(booked_h, 2),
                    "available_hours": round(available_h, 2),
                    "rate": round(booked_h / available_h, 4) if available_h else 0,
                },
            }
        )


class RevenueByDayView(BaseAnalyticsView):
    def get(self, request):
        d, venues = self.parse(request)
        rows = (
            Payment.objects.filter(booking__court__venue__in=venues, paid_at__date__range=(d["date_from"], d["date_to"]))
            .annotate(day=TruncDate("paid_at"))
            .values("day")
            .annotate(gross=Sum("amount"), refunded=Sum("refunded_amount"), payments=Count("id"))
            .order_by("day")
        )
        return Response([{**r, "net": r["gross"] - r["refunded"]} for r in rows])


class TopCourtsView(BaseAnalyticsView):
    def get(self, request):
        d, venues = self.parse(request)
        rows = (
            Booking.objects.filter(
                court__venue__in=venues, status__in=REVENUE_STATUSES,
                start_time__date__range=(d["date_from"], d["date_to"]),
            )
            .values("court_id", "court__name", "court__venue__name")
            .annotate(bookings=Count("id"), revenue=Sum("total_amount"))
            .order_by("-revenue")[:10]
        )
        return Response(list(rows))
