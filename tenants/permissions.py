from rest_framework.permissions import SAFE_METHODS, BasePermission

from .context import resolve_membership
from .models import Role


class IsHumanUser(BasePermission):
    """Signed-in person (not an API key)."""

    def has_permission(self, request, view):
        from accounts.models import User

        return isinstance(request.user, User) and request.user.is_authenticated


class IsBusinessMember(BasePermission):
    """Require membership of the active business, with a minimum role.

    Views set ``read_role`` (default VIEWER) and ``write_role`` (default ADMIN),
    or ``action_roles = {"action_name": Role.X}`` for per-action overrides.
    """

    def has_permission(self, request, view):
        membership = resolve_membership(request)
        action = getattr(view, "action", None)
        action_roles = getattr(view, "action_roles", {}) or {}
        if action in action_roles:
            required = action_roles[action]
        elif request.method in SAFE_METHODS:
            required = getattr(view, "read_role", Role.VIEWER)
        else:
            required = getattr(view, "write_role", Role.ADMIN)
        return membership.has_role(required)
