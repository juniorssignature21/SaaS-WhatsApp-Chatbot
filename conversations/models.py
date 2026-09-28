from django.conf import settings
from django.db import models
from django.utils import timezone

from tenants.models import BusinessOwnedModel


class Channel(models.TextChoices):
    WHATSAPP = "WHATSAPP"
    # Future channel adapters (TELEGRAM, INSTAGRAM, WEBCHAT...) plug in here
    # without touching the AI engine.


class Conversation(BusinessOwnedModel):
    class Status(models.TextChoices):
        OPEN = "OPEN"
        AI_HANDLING = "AI_HANDLING"
        WAITING_FOR_CUSTOMER = "WAITING_FOR_CUSTOMER"
        HUMAN_HANDLING = "HUMAN_HANDLING"
        RESOLVED = "RESOLVED"
        CLOSED = "CLOSED"

    ACTIVE_STATUSES = [
        Status.OPEN, Status.AI_HANDLING, Status.WAITING_FOR_CUSTOMER, Status.HUMAN_HANDLING,
    ]

    customer = models.ForeignKey("customers.Customer", on_delete=models.CASCADE, related_name="conversations")
    channel = models.CharField(max_length=16, choices=Channel.choices, default=Channel.WHATSAPP)
    whatsapp_account = models.ForeignKey(
        "whatsapp.WhatsAppAccount", null=True, blank=True, on_delete=models.SET_NULL, related_name="conversations"
    )
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.AI_HANDLING)
    assigned_agent = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="assigned_conversations",
    )
    handoff_reason = models.CharField(max_length=500, blank=True)
    started_at = models.DateTimeField(default=timezone.now)
    last_message_at = models.DateTimeField(default=timezone.now)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["business", "status", "-last_message_at"]),
            models.Index(fields=["business", "customer", "-last_message_at"]),
        ]

    def __str__(self):
        return f"Conversation {self.pk} ({self.status})"

    @property
    def ai_enabled(self):
        return self.status in {self.Status.OPEN, self.Status.AI_HANDLING, self.Status.WAITING_FOR_CUSTOMER}


class Message(BusinessOwnedModel):
    class Role(models.TextChoices):
        USER = "USER"  # the end-customer
        ASSISTANT = "ASSISTANT"  # the AI
        AGENT = "AGENT"  # a human team member
        SYSTEM = "SYSTEM"
        TOOL = "TOOL"

    class Direction(models.TextChoices):
        INBOUND = "INBOUND"
        OUTBOUND = "OUTBOUND"
        INTERNAL = "INTERNAL"

    class Type(models.TextChoices):
        TEXT = "text"
        IMAGE = "image"
        AUDIO = "audio"
        VIDEO = "video"
        DOCUMENT = "document"
        STICKER = "sticker"
        LOCATION = "location"
        CONTACTS = "contacts"
        INTERACTIVE = "interactive"
        BUTTON = "button"
        TEMPLATE = "template"
        REACTION = "reaction"
        UNSUPPORTED = "unsupported"

    class Status(models.TextChoices):
        RECEIVED = "RECEIVED"
        PENDING = "PENDING"
        SENT = "SENT"
        DELIVERED = "DELIVERED"
        READ = "READ"
        FAILED = "FAILED"

    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="messages")
    role = models.CharField(max_length=16, choices=Role.choices)
    direction = models.CharField(max_length=16, choices=Direction.choices)
    message_type = models.CharField(max_length=16, choices=Type.choices, default=Type.TEXT)
    content = models.TextField(blank=True)
    external_id = models.CharField(max_length=128, blank=True, help_text="Channel message id (e.g. wamid).")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    error = models.TextField(blank=True)
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["created_at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["business", "external_id"],
                condition=~models.Q(external_id=""),
                name="unique_external_message_id_per_business",
            )
        ]
        indexes = [models.Index(fields=["conversation", "created_at"])]

    def __str__(self):
        return f"{self.role}: {self.content[:40]}"
