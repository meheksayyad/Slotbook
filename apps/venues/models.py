from functools import cached_property
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils.text import slugify

from apps.common.models import TimeStampedModel


class Venue(TimeStampedModel):
    """A sports facility (e.g. a turf complex) that owns one or more courts."""

    SLOT_CHOICES = [(30, "30 minutes"), (60, "60 minutes")]

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="venues")
    name = models.CharField(max_length=150)
    slug = models.SlugField(max_length=170, unique=True, blank=True)
    description = models.TextField(blank=True)
    address = models.CharField(max_length=255)
    city = models.CharField(max_length=80, db_index=True)
    timezone = models.CharField(max_length=64, default="Asia/Kolkata")
    opening_time = models.TimeField()
    closing_time = models.TimeField()
    slot_minutes = models.PositiveSmallIntegerField(choices=SLOT_CHOICES, default=60)
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.CheckConstraint(condition=models.Q(opening_time__lt=models.F("closing_time")), name="venue_open_before_close"),
        ]

    def __str__(self):
        return self.name

    @cached_property
    def tz(self):
        return ZoneInfo(self.timezone)

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name) or "venue"
            slug, n = base, 1
            while Venue.objects.filter(slug=slug).exists():
                n += 1
                slug = f"{base}-{n}"
            self.slug = slug
        super().save(*args, **kwargs)


class Court(TimeStampedModel):
    class Sport(models.TextChoices):
        FOOTBALL = "football", "Football"
        CRICKET = "cricket", "Cricket"
        BADMINTON = "badminton", "Badminton"
        TENNIS = "tennis", "Tennis"
        BASKETBALL = "basketball", "Basketball"
        PICKLEBALL = "pickleball", "Pickleball"
        OTHER = "other", "Other"

    venue = models.ForeignKey(Venue, on_delete=models.CASCADE, related_name="courts")
    name = models.CharField(max_length=100)
    sport = models.CharField(max_length=20, choices=Sport.choices, db_index=True)
    base_price_per_hour = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(1)])
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["venue_id", "name"]
        constraints = [models.UniqueConstraint(fields=["venue", "name"], name="uniq_court_name_per_venue")]

    def __str__(self):
        return f"{self.venue.name} / {self.name}"


class PricingRule(TimeStampedModel):
    """Time-of-day / day-type multiplier. Court-specific rules beat venue-wide rules at equal priority."""

    class DayType(models.TextChoices):
        ANY = "any", "Any day"
        WEEKDAY = "weekday", "Weekday (Mon-Fri)"
        WEEKEND = "weekend", "Weekend (Sat-Sun)"

    venue = models.ForeignKey(Venue, on_delete=models.CASCADE, related_name="pricing_rules")
    court = models.ForeignKey(Court, on_delete=models.CASCADE, null=True, blank=True, related_name="pricing_rules")
    name = models.CharField(max_length=100)
    day_type = models.CharField(max_length=10, choices=DayType.choices, default=DayType.ANY)
    start_time = models.TimeField()
    end_time = models.TimeField()
    multiplier = models.DecimalField(
        max_digits=4, decimal_places=2, validators=[MinValueValidator(0.1), MaxValueValidator(5)]
    )
    priority = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-priority", "start_time"]
        constraints = [
            models.CheckConstraint(condition=models.Q(start_time__lt=models.F("end_time")), name="rule_start_before_end"),
        ]

    def __str__(self):
        return f"{self.name} x{self.multiplier}"
