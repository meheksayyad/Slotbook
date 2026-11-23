from datetime import time

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.accounts.models import User
from apps.venues.models import Court, PricingRule, Venue

PASSWORD = "Passw0rd!123"  # demo data only


class Command(BaseCommand):
    help = "Create demo users, a venue, courts and pricing rules (idempotent)."

    @transaction.atomic
    def handle(self, *args, **opts):
        admin, _ = User.objects.get_or_create(
            email="admin@slotbook.test", defaults={"role": "admin", "is_staff": True, "is_superuser": True}
        )
        owner, _ = User.objects.get_or_create(email="owner@slotbook.test", defaults={"role": "venue_owner", "first_name": "Olivia"})
        cust, _ = User.objects.get_or_create(email="customer@slotbook.test", defaults={"first_name": "Chris"})
        for u in (admin, owner, cust):
            u.set_password(PASSWORD)
            u.save()

        venue, _ = Venue.objects.get_or_create(
            name="Metro Sports Arena",
            defaults=dict(owner=owner, address="12 Stadium Road", city="Mumbai", opening_time=time(6), closing_time=time(23), slot_minutes=60),
        )
        for name, sport, price in [("Turf A (5-a-side)", "football", 1200), ("Turf B (7-a-side)", "football", 1800), ("Badminton 1", "badminton", 500)]:
            Court.objects.get_or_create(venue=venue, name=name, defaults=dict(sport=sport, base_price_per_hour=price))
        rules = [
            ("Weekday evening peak", "weekday", time(18), time(22), "1.40", 10),
            ("Weekend all-day", "weekend", time(6), time(23), "1.25", 5),
            ("Early-bird discount", "weekday", time(6), time(9), "0.80", 5),
        ]
        for name, dt, s, e, m, p in rules:
            PricingRule.objects.get_or_create(
                venue=venue, name=name, defaults=dict(day_type=dt, start_time=s, end_time=e, multiplier=m, priority=p)
            )
        self.stdout.write(self.style.SUCCESS(f"Seeded. Logins (password {PASSWORD}): admin@/owner@/customer@slotbook.test"))
