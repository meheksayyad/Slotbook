from rest_framework.permissions import SAFE_METHODS, BasePermission


class IsVenueManager(BasePermission):
    """Venue owners and platform admins."""

    def has_permission(self, request, view):
        u = request.user
        return bool(u and u.is_authenticated and u.is_venue_manager)


class IsVenueManagerOrReadOnly(BasePermission):
    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        u = request.user
        return bool(u and u.is_authenticated and u.is_venue_manager)
