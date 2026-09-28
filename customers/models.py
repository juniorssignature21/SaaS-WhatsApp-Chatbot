from django.db import models

from tenants.models import BusinessOwnedModel


class Customer(BusinessOwnedModel):
    """An end-customer chatting with a business (not a SaaS user).

    The same phone number is a *different* Customer in each business.
    """

    phone_number = models.CharField(max_length=32, help_text="E.164 digits, as reported by WhatsApp.")
    name = models.CharField(max_length=200, blank=True)
    email = models.EmailField(blank=True)
    external_id = models.CharField(max_length=128, blank=True, help_text="ID in the business's own CRM.")
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["business", "phone_number"], name="unique_customer_phone_per_business")
        ]
        indexes = [models.Index(fields=["business", "-updated_at"])]

    def __str__(self):
        return self.name or self.phone_number
