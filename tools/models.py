import secrets

from django.core.validators import RegexValidator
from django.db import models

from common.fields import EncryptedTextField
from tenants.models import BusinessOwnedModel

tool_name_validator = RegexValidator(
    r"^[a-z][a-z0-9_]{0,63}$", "Use lowercase letters, digits and underscores (e.g. check_order_status)."
)


def generate_signing_secret():
    return secrets.token_urlsafe(32)


class Tool(BusinessOwnedModel):
    """A business-defined tool the AI can call, backed by the business's own API.

    When the AI calls it, we POST a signed JSON request to ``endpoint_url``
    (see tools.executors.HttpToolExecutor) and pass the JSON response back.
    Examples: check_order_status, book_appointment, get_product, check_balance.
    """

    class Method(models.TextChoices):
        POST = "POST"
        GET = "GET"

    name = models.CharField(max_length=64, validators=[tool_name_validator])
    description = models.TextField(help_text="Tells the AI when and how to use this tool.")
    input_schema = models.JSONField(
        default=dict, blank=True,
        help_text=(
            'JSON Schema for the arguments, e.g. '
            '{"type":"object","properties":{"order_id":{"type":"string"}},"required":["order_id"]}'
        ),
    )
    endpoint_url = models.URLField()
    http_method = models.CharField(max_length=8, choices=Method.choices, default=Method.POST)
    signing_secret = EncryptedTextField(default=generate_signing_secret)
    timeout_seconds = models.PositiveSmallIntegerField(default=10)
    enabled = models.BooleanField(default=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["business", "name"], name="unique_tool_name_per_business")]

    def __str__(self):
        return self.name
