"""Tenant resolution and role checks for the server-rendered dashboard.

The active business is stored in the session but always re-validated
against the signed-in user's memberships on every request.
"""

from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect

from tenants.models import Business, Membership, Role

SESSION_KEY = "active_business_id"


def get_membership(request):
    memberships = Membership.objects.select_related("business").filter(user=request.user)
    business_id = request.session.get(SESSION_KEY)
    membership = memberships.filter(business_id=business_id).first() if business_id else None
    if membership is None:
        membership = memberships.order_by("created_at").first()
        if membership:
            request.session[SESSION_KEY] = membership.business_id
    return membership


def member_required(role=Role.VIEWER):
    """View decorator: sets ``request.membership`` and ``request.business``."""

    def decorator(view):
        @login_required
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            membership = get_membership(request)
            if membership is None:
                return redirect("dashboard:create_business")
            if membership.business.status != Business.Status.ACTIVE:
                messages.error(request, "This business is suspended. Contact support.")
                raise PermissionDenied
            if not membership.has_role(role):
                raise PermissionDenied
            request.membership = membership
            request.business = membership.business
            return view(request, *args, **kwargs)

        wrapper.required_role = role
        return wrapper

    return decorator


def can(request, role):
    membership = getattr(request, "membership", None)
    return bool(membership and membership.has_role(role))
