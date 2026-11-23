from django.urls import include, path
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView

from apps.accounts.views import LoginView, MeView, RegisterView
from apps.analytics.views import RevenueByDayView, SummaryView, TopCourtsView
from apps.bookings.views import BookingViewSet
from apps.payments.views import PaymentListView, WebhookView
from apps.venues.views import CourtViewSet, PricingRuleViewSet, VenueViewSet

router = DefaultRouter()
router.register("venues", VenueViewSet, basename="venue")
router.register("courts", CourtViewSet, basename="court")
router.register("pricing-rules", PricingRuleViewSet, basename="pricing-rule")
router.register("bookings", BookingViewSet, basename="booking")

urlpatterns = [
    path("auth/register/", RegisterView.as_view(), name="register"),
    path("auth/token/", LoginView.as_view(), name="token"),
    path("auth/token/refresh/", TokenRefreshView.as_view(), name="token-refresh"),
    path("auth/me/", MeView.as_view(), name="me"),
    path("payments/", PaymentListView.as_view(), name="payment-list"),
    path("payments/webhook/", WebhookView.as_view(), name="payment-webhook"),
    path("analytics/summary/", SummaryView.as_view(), name="analytics-summary"),
    path("analytics/revenue-by-day/", RevenueByDayView.as_view(), name="analytics-revenue"),
    path("analytics/top-courts/", TopCourtsView.as_view(), name="analytics-top-courts"),
    path("", include(router.urls)),
]
