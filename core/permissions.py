from rest_framework.permissions import BasePermission


class IsModerator(BasePermission):
    """Moderator role, admin role, superuser, or reputation above the threshold (see User.can_moderate)."""

    message = "Only moderators can do this."

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.can_moderate)


def is_moderator(user):
    return bool(user and user.is_authenticated and user.can_moderate)
