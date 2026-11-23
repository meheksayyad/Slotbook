from rest_framework.exceptions import APIException
from rest_framework.views import exception_handler as drf_exception_handler


class DomainError(APIException):
    status_code = 400
    default_code = "domain_error"
    default_detail = "Request could not be processed."


class InvalidBookingRequest(DomainError):
    default_code = "invalid_booking_request"


class SlotUnavailable(DomainError):
    status_code = 409
    default_code = "slot_unavailable"
    default_detail = "The selected slot is no longer available."


class InvalidBookingState(DomainError):
    status_code = 409
    default_code = "invalid_booking_state"


class PaymentError(DomainError):
    default_code = "payment_error"


class GatewayError(Exception):
    """Raised by gateway adapters when the upstream provider fails."""


def exception_handler(exc, context):
    """Uniform error envelope: {"error": {"code", "message", "details"}}."""
    response = drf_exception_handler(exc, context)
    if response is None:
        return None
    data = response.data
    code = getattr(exc, "default_code", "error")
    if isinstance(data, dict) and set(data.keys()) == {"detail"}:
        message, details = str(data["detail"]), None
    else:
        message = "Validation failed." if response.status_code == 400 else "Request failed."
        details = data
    response.data = {"error": {"code": code, "message": message, "details": details}}
    return response
