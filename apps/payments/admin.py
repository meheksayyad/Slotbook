from django.contrib import admin

from .models import Payment, Refund


class RefundInline(admin.TabularInline):
    model = Refund
    extra = 0
    readonly_fields = ("amount", "status", "provider_refund_id", "reason")
    can_delete = False


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("provider_order_id", "booking", "amount", "refunded_amount", "status", "paid_at")
    list_filter = ("status", "provider")
    search_fields = ("provider_order_id", "provider_payment_id", "booking__reference")
    inlines = [RefundInline]
