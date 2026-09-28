from django.db import models

from common.models import TimeStampedModel
from tenants.models import Business


class Plan(TimeStampedModel):
    """A subscription tier. ``None`` in a limit field means unlimited."""

    code = models.SlugField(unique=True)
    name = models.CharField(max_length=100)
    price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    currency = models.CharField(max_length=3, default="NGN")
    max_whatsapp_numbers = models.PositiveIntegerField(null=True, blank=True)
    max_team_members = models.PositiveIntegerField(null=True, blank=True)
    max_knowledge_documents = models.PositiveIntegerField(null=True, blank=True)
    monthly_conversations = models.PositiveIntegerField(null=True, blank=True)
    monthly_ai_responses = models.PositiveIntegerField(null=True, blank=True)
    features = models.JSONField(default=dict, blank=True, help_text='e.g. {"rag": true, "tools": false}')
    is_public = models.BooleanField(default=True)
    interval_days = models.PositiveSmallIntegerField(default=30)
    paystack_plan_code = models.CharField(
        max_length=64, blank=True, help_text="PLN_... code of the matching plan in the Paystack dashboard."
    )

    def __str__(self):
        return self.name

    def has_feature(self, feature):
        return bool(self.features.get(feature, False))


class Subscription(TimeStampedModel):
    class Status(models.TextChoices):
        TRIALING = "TRIALING"
        ACTIVE = "ACTIVE"
        PAST_DUE = "PAST_DUE"
        CANCELED = "CANCELED"

    business = models.OneToOneField(Business, on_delete=models.CASCADE, related_name="subscription")
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name="subscriptions")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.TRIALING)
    current_period_start = models.DateTimeField(null=True, blank=True)
    current_period_end = models.DateTimeField(null=True, blank=True)
    external_id = models.CharField(max_length=128, blank=True, help_text="Payment provider subscription id.")
    trial_ends_at = models.DateTimeField(null=True, blank=True)
    cancel_at_period_end = models.BooleanField(default=False)
    paystack_customer_code = models.CharField(max_length=64, blank=True, db_index=True)
    paystack_email_token = models.CharField(max_length=64, blank=True)

    def __str__(self):
        return f"{self.business} on {self.plan} ({self.status})"

    @property
    def is_usable(self):
        return self.status in {self.Status.TRIALING, self.Status.ACTIVE}


class UsageRecord(models.Model):
    """Monthly usage counters per business; drives analytics and billing."""

    COUNTERS = [
        "conversations", "resolved_conversations", "messages_in", "messages_out",
        "ai_responses", "human_responses", "escalations", "tool_calls",
        "input_tokens", "output_tokens", "cache_read_tokens",
    ]

    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name="usage_records")
    period = models.DateField(help_text="First day of the month.")
    conversations = models.PositiveIntegerField(default=0)
    resolved_conversations = models.PositiveIntegerField(default=0)
    messages_in = models.PositiveIntegerField(default=0)
    messages_out = models.PositiveIntegerField(default=0)
    ai_responses = models.PositiveIntegerField(default=0)
    human_responses = models.PositiveIntegerField(default=0)
    escalations = models.PositiveIntegerField(default=0)
    tool_calls = models.PositiveIntegerField(default=0)
    input_tokens = models.PositiveBigIntegerField(default=0)
    output_tokens = models.PositiveBigIntegerField(default=0)
    cache_read_tokens = models.PositiveBigIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["business", "period"], name="unique_usage_period")]
        ordering = ["-period"]

    def __str__(self):
        return f"{self.business} {self.period:%Y-%m}"


class Payment(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING"
        SUCCESS = "SUCCESS"
        FAILED = "FAILED"

    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name="payments")
    plan = models.ForeignKey(Plan, null=True, on_delete=models.SET_NULL)
    provider = models.CharField(max_length=16, default="paystack")
    reference = models.CharField(max_length=100, unique=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, default="NGN")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    paid_at = models.DateTimeField(null=True, blank=True)
    raw = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.reference} {self.amount} {self.currency} ({self.status})"
