from drf_spectacular.utils import extend_schema
from rest_framework import generics
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from . import services
from .gateways import get_gateway
from .models import Payment
from .serializers import PaymentSerializer


class PaymentListView(generics.ListAPIView):
    serializer_class = PaymentSerializer
    filterset_fields = ["status", "booking"]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Payment.objects.none()
        qs = Payment.objects.select_related("booking")
        return qs if self.request.user.is_admin_role else qs.filter(booking__user=self.request.user)


class WebhookView(APIView):
    """Gateway -> server callback. Authenticated by HMAC signature, not by JWT."""

    authentication_classes: list = []
    permission_classes = [AllowAny]
    throttle_classes: list = []

    @extend_schema(exclude=True)
    def post(self, request):
        signature = request.headers.get(get_gateway().signature_header, "")
        try:
            result = services.handle_webhook(request.body, signature)
        except services.InvalidSignature:
            return Response({"error": {"code": "invalid_signature", "message": "Bad signature.", "details": None}}, status=400)
        return Response({"status": result})
