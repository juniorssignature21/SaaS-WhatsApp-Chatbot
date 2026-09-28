"""Resolve the active tenant for an API request.

The tenant is never taken on trust from the client: the optional
``X-Business-ID`` header only *selects* among businesses the authenticated
user is already a member of.
"""

from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError

from .models import APIKey, Business, Membership

BUSINESS_HEADER = "HTTP_X_BUSINESS_ID"


def resolve_membership(request):
    if hasattr(request, "_tenant_membership"):
        return request._tenant_membership

    user = request.user
    if not user or not user.is_authenticated:
        raise PermissionDenied("Authentication required.")

    if isinstance(getattr(request, "auth", None), APIKey):
        membership = _api_key_membership(request, request.auth)
        request._tenant_membership = membership
        return membership

    memberships = Membership.objects.select_related("business").filter(user=user)
    selector = request.META.get(BUSINESS_HEADER, "").strip()
    if selector:
        lookup = {"business__id": selector} if selector.isdigit() else {"business__slug": selector}
        membership = memberships.filter(**lookup).first()
        if membership is None:
            # Same response whether the business exists or not: don't leak tenants.
            raise NotFound("Business not found.")
    else:
        found = list(memberships[:2])
        if not found:
            raise PermissionDenied("You are not a member of any business.")
        if len(found) > 1:
            raise ValidationError({"detail": "Multiple businesses; send the X-Business-ID header."})
        membership = found[0]

    if membership.business.status != Business.Status.ACTIVE:
        raise PermissionDenied("This business is suspended.")

    request._tenant_membership = membership
    return membership


def _api_key_membership(request, key):
    from billing.services import has_feature

    selector = request.META.get(BUSINESS_HEADER, "").strip()
    if selector and selector not in {str(key.business_id), key.business.slug}:
        raise NotFound("Business not found.")
    if key.business.status != Business.Status.ACTIVE:
        raise PermissionDenied("This business is suspended.")
    if not has_feature(key.business, "api_access"):
        raise PermissionDenied("API access is not included in your plan.")
    # Unsaved membership: the key acts with its own role inside its own business only.
    return Membership(business=key.business, role=key.role)


def acting_user(request):
    """The human user behind a request, or None for API-key requests."""
    from accounts.models import User

    return request.user if isinstance(request.user, User) else None
