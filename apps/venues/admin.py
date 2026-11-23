from django.contrib import admin

from .models import Court, PricingRule, Venue


class CourtInline(admin.TabularInline):
    model = Court
    extra = 0


@admin.register(Venue)
class VenueAdmin(admin.ModelAdmin):
    list_display = ("name", "city", "owner", "opening_time", "closing_time", "is_active")
    list_filter = ("city", "is_active")
    search_fields = ("name", "city")
    inlines = [CourtInline]


@admin.register(Court)
class CourtAdmin(admin.ModelAdmin):
    list_display = ("name", "venue", "sport", "base_price_per_hour", "is_active")
    list_filter = ("sport", "is_active")


@admin.register(PricingRule)
class PricingRuleAdmin(admin.ModelAdmin):
    list_display = ("name", "venue", "court", "day_type", "start_time", "end_time", "multiplier", "priority")
    list_filter = ("day_type", "is_active")
