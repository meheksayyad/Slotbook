from datetime import time, timedelta
from decimal import Decimal

from apps.venues import pricing

from .conftest import slot_start
from .factories import make_booking

HOUR = timedelta(hours=1)


def test_base_price_without_rules(court, venue):
    s = slot_start(venue, 12, weekday=1)
    q = pricing.quote(court, s, s + HOUR)
    assert q["total"] == Decimal("1000.00") and q["slots"][0]["rule"] is None


def test_weekday_peak_rule(court, venue, make_rule):
    make_rule(name="Peak", day_type="weekday", start_time=time(18), end_time=time(22), multiplier=Decimal("1.40"), priority=10)
    s = slot_start(venue, 19, weekday=0)
    q = pricing.quote(court, s, s + 2 * HOUR)
    assert q["total"] == Decimal("2800.00")
    assert [x["rule"] for x in q["slots"]] == ["Peak", "Peak"]


def test_weekend_rule_not_applied_on_weekday(court, venue, make_rule):
    make_rule(name="Weekend", day_type="weekend", multiplier=Decimal("1.25"))
    weekday = slot_start(venue, 10, weekday=2)
    saturday = slot_start(venue, 10, weekday=5)
    assert pricing.quote(court, weekday, weekday + HOUR)["total"] == Decimal("1000.00")
    assert pricing.quote(court, saturday, saturday + HOUR)["total"] == Decimal("1250.00")


def test_court_specific_rule_beats_venue_rule_at_equal_priority(court, venue, make_rule):
    make_rule(name="Venue-wide", multiplier=Decimal("1.20"), priority=5)
    make_rule(name="Court-only", court=court, multiplier=Decimal("1.50"), priority=5)
    s = slot_start(venue, 10, weekday=1)
    assert pricing.quote(court, s, s + HOUR)["total"] == Decimal("1500.00")


def test_higher_priority_wins(court, venue, make_rule):
    make_rule(name="Low", multiplier=Decimal("2.00"), priority=1)
    make_rule(name="High", multiplier=Decimal("0.80"), priority=9)
    s = slot_start(venue, 10, weekday=1)
    assert pricing.quote(court, s, s + HOUR)["total"] == Decimal("800.00")


def test_demand_surge_when_day_is_busy(court, venue, customer):
    day_start = slot_start(venue, 6, weekday=1)
    make_booking(customer, court, day_start, hours=12)  # 12h of a 17h day = 70.6% utilisation
    late = slot_start(venue, 19, weekday=1)
    slot = pricing.quote(court, late, late + HOUR)["slots"][0]
    assert slot["surge"] is True and slot["price"] == Decimal("1150.00")


def test_no_surge_below_threshold(court, venue, customer):
    make_booking(customer, court, slot_start(venue, 6, weekday=1), hours=4)
    late = slot_start(venue, 19, weekday=1)
    assert pricing.quote(court, late, late + HOUR)["slots"][0]["surge"] is False


def test_multiplier_is_capped(court, venue, customer, make_rule):
    make_rule(name="Huge", multiplier=Decimal("2.40"))
    make_booking(customer, court, slot_start(venue, 6, weekday=1), hours=12)
    late = slot_start(venue, 19, weekday=1)
    assert pricing.quote(court, late, late + HOUR)["slots"][0]["multiplier"] == Decimal("2.50")
