from datetime import datetime, time, timedelta
from decimal import Decimal

import pytest
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.venues.models import Court, PricingRule, Venue

PASSWORD = "S3cure-pass!word"


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


def _user(email, role="customer"):
    return User.objects.create_user(email, PASSWORD, role=role, first_name=email.split("@")[0].title())


@pytest.fixture
def owner(db):
    return _user("owner@test.com", "venue_owner")


@pytest.fixture
def other_owner(db):
    return _user("owner2@test.com", "venue_owner")


@pytest.fixture
def customer(db):
    return _user("alice@test.com")


@pytest.fixture
def other_customer(db):
    return _user("bob@test.com")


@pytest.fixture
def admin(db):
    return _user("admin@test.com", "admin")


@pytest.fixture
def venue(owner):
    return Venue.objects.create(
        owner=owner, name="Test Arena", address="1 Main St", city="Mumbai",
        opening_time=time(6), closing_time=time(23), slot_minutes=60,
    )


@pytest.fixture
def court(venue):
    return Court.objects.create(venue=venue, name="Turf A", sport="football", base_price_per_hour=Decimal("1000.00"))


@pytest.fixture
def make_rule(venue):
    def _make(**kw):
        defaults = dict(venue=venue, name="rule", day_type="any", start_time=time(0, 0), end_time=time(23, 59), multiplier=Decimal("1.00"))
        return PricingRule.objects.create(**{**defaults, **kw})
    return _make


@pytest.fixture
def client_for():
    def _client(user=None):
        c = APIClient()
        if user:
            c.force_authenticate(user)
        return c
    return _client


def slot_start(venue, hour, *, weekday=None, min_days=3):
    """Aware datetime in the venue's tz: `hour`:00 on a future date (optionally a given weekday, Mon=0)."""
    d = timezone.now().astimezone(venue.tz).date() + timedelta(days=min_days)
    if weekday is not None:
        while d.weekday() != weekday:
            d += timedelta(days=1)
    return datetime.combine(d, time(hour), tzinfo=venue.tz)
