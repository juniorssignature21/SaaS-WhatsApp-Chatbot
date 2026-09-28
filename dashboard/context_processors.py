from django.conf import settings

from notifications.services import unread_count
from tenants.models import Membership, Role


def dashboard(request):
    membership = getattr(request, "membership", None)
    if membership is None:
        return {"platform_name": settings.PLATFORM_NAME}
    business = membership.business
    return {
        "platform_name": settings.PLATFORM_NAME,
        "brand_name": business.brand_name or settings.PLATFORM_NAME,
        "brand_color": business.brand_color or "#0f766e",
        "business": business,
        "membership": membership,
        "all_memberships": Membership.objects.filter(user=request.user).select_related("business"),
        "unread_notifications": unread_count(request.user, business),
        "is_agent": membership.has_role(Role.AGENT),
        "is_admin": membership.has_role(Role.ADMIN),
        "is_owner": membership.has_role(Role.OWNER),
    }
