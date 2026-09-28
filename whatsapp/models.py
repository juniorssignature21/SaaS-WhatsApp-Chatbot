import re

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


class MessageTemplate(BusinessOwnedModel):
    """A pre-approved WhatsApp message template, synced from Meta.

    Templates are the only way to message a customer outside the 24-hour
    customer-service window. Body variables ({{1}}, {{2}}...) are filled per send.
    """

    whatsapp_account = models.ForeignKey(WhatsAppAccount, on_delete=models.CASCADE, related_name="templates")
    external_id = models.CharField(max_length=64, blank=True)
    name = models.CharField(max_length=512)
    language = models.CharField(max_length=16)
    category = models.CharField(max_length=32, blank=True)
    status = models.CharField(max_length=32, help_text="APPROVED, PENDING, REJECTED, PAUSED...")
    components = models.JSONField(default=list, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["whatsapp_account", "name", "language"], name="unique_template_per_number")
        ]
        ordering = ["name", "language"]

    def __str__(self):
        return f"{self.name} ({self.language})"

    VARIABLE_RE = re.compile(r"\{\{\s*(\d+)\s*\}\}")

    def _component(self, kind):
        return next((c for c in self.components if str(c.get("type", "")).upper() == kind), None)

    @property
    def body_text(self):
        body = self._component("BODY")
        return body.get("text", "") if body else ""

    @property
    def parameter_count(self):
        return len(set(self.VARIABLE_RE.findall(self.body_text)))

    @property
    def is_sendable(self):
        """Approved, and no header variables (header media/params are not supported yet)."""
        header = self._component("HEADER")
        header_has_params = bool(header) and (
            header.get("format", "TEXT").upper() != "TEXT" or self.VARIABLE_RE.search(header.get("text", ""))
        )
        return self.status == "APPROVED" and not header_has_params

    def render(self, params):
        return self.VARIABLE_RE.sub(lambda m: params[int(m.group(1)) - 1], self.body_text)
