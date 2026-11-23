from django.conf import settings
from django.core.mail import send_mail


def _when(b):
    tz = b.court.venue.tz
    return f"{b.start_time.astimezone(tz):%a %d %b %Y, %H:%M}-{b.end_time.astimezone(tz):%H:%M}"


def _send(b, subject, body):
    send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [b.user.email], fail_silently=False)


def send_confirmation(b):
    _send(
        b,
        f"Booking confirmed - {b.reference}",
        f"Hi {b.user.first_name or 'there'},\n\nYour booking is confirmed.\n\n"
        f"Venue: {b.court.venue.name}\nCourt: {b.court.name}\nWhen: {_when(b)}\n"
        f"Amount paid: {b.total_amount}\nReference: {b.reference}\n\nSee you on the field!\n- SlotBook",
    )


def send_reminder(b):
    _send(
        b,
        f"Reminder: your game at {b.court.venue.name} is coming up",
        f"Hi {b.user.first_name or 'there'},\n\nFriendly reminder of your booking {b.reference}:\n"
        f"{b.court.venue.name} - {b.court.name}\n{_when(b)}\n\n- SlotBook",
    )


def send_cancellation(b):
    _send(
        b,
        f"Booking cancelled - {b.reference}",
        f"Hi {b.user.first_name or 'there'},\n\nBooking {b.reference} ({_when(b)}) was cancelled.\n"
        f"Refund: {b.refund_amount} (processed to your original payment method).\n\n- SlotBook",
    )


SENDERS = {"confirmed": send_confirmation, "reminder": send_reminder, "cancelled": send_cancellation}
