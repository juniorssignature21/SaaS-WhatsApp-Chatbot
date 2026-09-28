from django.db import models

from common.fields import EncryptedTextField
from tenants.models import BusinessOwnedModel


class WhatsAppAccount(BusinessOwnedModel):
    """A WhatsApp Business phone number connected by a tenant.

    Inbound webhooks are routed to the right tenant by ``phone_number_id``,
    which is globally unique.
    """

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE"
        DISABLED = "DISABLED"

    display_name = models.CharField(max_length=200, blank=True)
    phone_number = models.CharField(max_length=32, help_text="Display phone number, e.g. +2348012345678.")
    phone_number_id = models.CharField(max_length=64, unique=True, help_text="Meta phone number ID.")
    business_account_id = models.CharField(max_length=64, help_text="WhatsApp Business Account (WABA) ID.")
    access_token = EncryptedTextField(help_text="System-user access token; encrypted at rest.")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    last_webhook_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.phone_number} ({self.business_id})"
