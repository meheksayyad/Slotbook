from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from .factories import make_booking, make_payment

pytestmark = pytest.mark.django_db


def test_summary_revenue_and_scoping(client_for, owner, other_owner, customer, court, venue):
    b = make_booking(customer, court, timezone.now() + timedelta(days=1), status="confirmed", amount="2000.00")
    p = make_payment(b)
    p.refunded_amount = Decimal("500.00")
    p.save()

    r = client_for(owner).get("/api/v1/analytics/summary/")
    assert r.status_code == 200
    assert Decimal(str(r.data["revenue"]["gross"])) == Decimal("2000.00")
    assert Decimal(str(r.data["revenue"]["net"])) == Decimal("1500.00")

    other = client_for(other_owner).get("/api/v1/analytics/summary/")
    assert Decimal(str(other.data["revenue"]["gross"])) == 0  # cannot see another owner's money


def test_analytics_forbidden_for_customers(client_for, customer):
    assert client_for(customer).get("/api/v1/analytics/summary/").status_code == 403


def test_range_validation(client_for, owner):
    r = client_for(owner).get("/api/v1/analytics/summary/?date_from=2020-01-01&date_to=2024-01-01")
    assert r.status_code == 400


def test_top_courts_and_daily_revenue(client_for, owner, customer, court):
    b = make_booking(customer, court, timezone.now() + timedelta(days=1), status="confirmed", amount="1000.00")
    make_payment(b)
    top = client_for(owner).get("/api/v1/analytics/top-courts/?date_to=" + (timezone.localdate() + timedelta(days=3)).isoformat())
    assert top.status_code == 200 and top.data[0]["bookings"] == 1
    daily = client_for(owner).get("/api/v1/analytics/revenue-by-day/")
    assert daily.status_code == 200 and len(daily.data) == 1
