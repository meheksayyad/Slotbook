"""Dynamic pricing engine.

price(slot) = base_price_per_hour * hours * min(rule_multiplier * surge, MAX_PRICE_MULTIPLIER)

* rule_multiplier : best matching PricingRule (priority, then court-specific over venue-wide)
* surge           : SURGE_MULTIPLIER if the court's utilisation for that day >= threshold (demand-based)
"""
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings

CENT = Decimal("0.01")
ONE = Decimal("1")


def money(value) -> Decimal:
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def iter_slots(start, end, minutes):
    step, cur = timedelta(minutes=minutes), start
    while cur < end:
        yield cur, cur + step
        cur += step


def load_rules(venue):
    return list(venue.pricing_rules.filter(is_active=True))


def day_window(venue, day):
    return (
        datetime.combine(day, venue.opening_time, tzinfo=venue.tz),
        datetime.combine(day, venue.closing_time, tzinfo=venue.tz),
    )


def day_utilisation(court, day) -> Decimal:
    """Fraction (0..1) of the court's opening hours already held/booked on `day`."""
    from apps.bookings.models import Booking

    open_dt, close_dt = day_window(court.venue, day)
    total = (close_dt - open_dt).total_seconds()
    if total <= 0:
        return Decimal("0")
    rows = Booking.objects.active().filter(
        court=court, start_time__lt=close_dt, end_time__gt=open_dt
    ).values_list("start_time", "end_time")
    booked = sum((min(e, close_dt) - max(s, open_dt)).total_seconds() for s, e in rows)
    return Decimal(str(round(booked / total, 4)))


def match_rule(rules, court, local_start):
    weekend = local_start.weekday() >= 5
    t, best, best_key = local_start.time(), None, None
    for r in rules:
        if r.court_id not in (None, court.id):
            continue
        if (r.day_type == "weekday" and weekend) or (r.day_type == "weekend" and not weekend):
            continue
        if not (r.start_time <= t < r.end_time):
            continue
        key = (r.priority, r.court_id is not None)
        if best_key is None or key > best_key:
            best, best_key = r, key
    return best


def price_slot(court, rules, start, end, utilisation) -> dict:
    local_start = start.astimezone(court.venue.tz)
    rule = match_rule(rules, court, local_start)
    multiplier = rule.multiplier if rule else ONE
    surge = utilisation >= settings.SURGE_UTILISATION_THRESHOLD
    if surge:
        multiplier = multiplier * settings.SURGE_MULTIPLIER
    multiplier = min(multiplier, settings.MAX_PRICE_MULTIPLIER)
    hours = Decimal(int((end - start).total_seconds())) / Decimal(3600)
    base = money(court.base_price_per_hour * hours)
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "base_price": base,
        "multiplier": multiplier.quantize(CENT),
        "rule": rule.name if rule else None,
        "surge": surge,
        "price": money(court.base_price_per_hour * hours * multiplier),
    }


def quote(court, start, end) -> dict:
    venue = court.venue
    rules, util, slots = load_rules(venue), {}, []
    for s, e in iter_slots(start, end, venue.slot_minutes):
        day = s.astimezone(venue.tz).date()
        if day not in util:
            util[day] = day_utilisation(court, day)
        slots.append(price_slot(court, rules, s, e, util[day]))
    total = money(sum((x["price"] for x in slots), Decimal("0")))
    return {"currency": settings.PAYMENT_CURRENCY, "slots": slots, "total": total}
