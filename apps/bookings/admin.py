from django.contrib import admin

from .models import Booking


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ("reference", "user", "court", "start_time", "end_time", "status", "total_amount")
    list_filter = ("status", "court__venue")
    search_fields = ("reference", "user__email")
    date_hierarchy = "start_time"
    readonly_fields = ("reference", "price_breakdown", "created_at", "updated_at")
