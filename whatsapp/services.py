from django.conf import settings
from django.db import transaction

from billing.services import check_limit

from .client import WhatsAppClient
from .models import MessageTemplate, WhatsAppAccount


class ConnectNotAllowed(Exception):
    pass


def assert_can_connect(business, user):
    if settings.REQUIRE_EMAIL_VERIFICATION and (user is None or not user.email_verified):
        raise ConnectNotAllowed("Verify your email address before connecting a WhatsApp number.")
    count = WhatsAppAccount.objects.filter(business=business).count()
    if not check_limit(business, "max_whatsapp_numbers", count):
        raise ConnectNotAllowed("Your plan's WhatsApp number limit has been reached. Upgrade to add more.")


@transaction.atomic
def sync_templates(account):
    """Mirror the number's WABA templates locally. Returns how many were synced."""
    remote = WhatsAppClient(account).list_templates()
    seen = set()
    for item in remote:
        key = (item.get("name", ""), item.get("language", ""))
        if not all(key):
            continue
        seen.add(key)
        MessageTemplate.objects.update_or_create(
            whatsapp_account=account, name=key[0], language=key[1],
            defaults={
                "business_id": account.business_id,
                "external_id": str(item.get("id", "")),
                "category": item.get("category", ""),
                "status": item.get("status", ""),
                "components": item.get("components", []),
            },
        )
    for template in MessageTemplate.objects.filter(whatsapp_account=account):
        if (template.name, template.language) not in seen:
            template.delete()
    return len(seen)
