from django.db import transaction
from django.utils.text import slugify

from .models import APIKey, AuditLog, Business, Membership, Role


def _unique_slug(name):
    base = slugify(name)[:60] or "business"
    slug, n = base, 1
    while Business.objects.filter(slug=slug).exists():
        n += 1
        slug = f"{base}-{n}"
    return slug


@transaction.atomic
def create_business(owner, name, **fields):
    """Create a tenant with its owner membership and default configuration."""
    from billing.services import start_default_subscription
    from chatbot.models import AIConfiguration

    business = Business.objects.create(name=name, slug=_unique_slug(name), **fields)
    Membership.objects.create(user=owner, business=business, role=Role.OWNER)
    AIConfiguration.objects.create(business=business, name=f"{name} Assistant")
    start_default_subscription(business)
    audit(business, owner, "business.created", business)
    return business


def audit(business, actor, action, target=None, request=None, **metadata):
    from accounts.models import User

    ip = None
    if request is not None:
        ip = request.META.get("REMOTE_ADDR")
        api_key = getattr(request, "auth", None)
        if isinstance(api_key, APIKey):
            metadata.setdefault("api_key", api_key.prefix)
    return AuditLog.objects.create(
        business=business,
        actor=actor if isinstance(actor, User) else None,
        action=action,
        target_type=type(target).__name__ if target is not None else "",
        target_id=str(getattr(target, "pk", "") or ""),
        metadata=metadata,
        ip_address=ip,
    )
