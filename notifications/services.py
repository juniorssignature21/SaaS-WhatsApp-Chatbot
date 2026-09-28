from django.conf import settings
from django.db import transaction
from django.urls import reverse

from tenants.models import Membership, Role

from .models import Notification


def notify_handoff(conversation, reason=""):
    """Tell the assigned agent - or every agent and above - that a customer needs a human."""
    members = Membership.objects.filter(business_id=conversation.business_id).select_related("user")
    if conversation.assigned_agent_id:
        members = members.filter(user_id=conversation.assigned_agent_id)
    else:
        members = [m for m in members if m.has_role(Role.AGENT)]
    customer = conversation.customer
    title = f"{customer.name or customer.phone_number} needs a human"
    link = settings.SITE_URL + reverse("dashboard:conversation", args=[conversation.id])
    emails = []
    for membership in members:
        Notification.objects.create(
            business_id=conversation.business_id, user=membership.user, kind=Notification.Kind.HANDOFF,
            title=title, body=reason, conversation=conversation,
        )
        if membership.notify_by_email and membership.user.is_active:
            emails.append(membership.user.email)
    if emails:
        from .tasks import send_notification_email

        body = f"{title}.\n\nReason: {reason or 'not given'}\n\nOpen the conversation: {link}"
        transaction.on_commit(lambda: send_notification_email.delay(emails, title, body))


def unread_count(user, business):
    return Notification.objects.filter(user=user, business=business, read_at__isnull=True).count()
