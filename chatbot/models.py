from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from common.models import TimeStampedModel
from tenants.models import Business


def default_model():
    return settings.CHATBOT_DEFAULT_MODEL


class AIConfiguration(TimeStampedModel):
    """Per-business assistant configuration: persona, model and behaviour."""

    class Effort(models.TextChoices):
        DEFAULT = "", "Model default"
        LOW = "low"
        MEDIUM = "medium"
        HIGH = "high"

    business = models.OneToOneField(Business, on_delete=models.CASCADE, related_name="ai_config")
    enabled = models.BooleanField(default=True, help_text="Turn the AI off to route everything to humans.")
    template = models.SlugField(blank=True, help_text="Template this bot was created from.")
    name = models.CharField(max_length=100, default="Assistant")
    system_prompt = models.TextField(
        blank=True, help_text="Business-specific instructions: personality, responsibilities, policies."
    )
    model = models.CharField(max_length=100, default=default_model)
    max_tokens = models.PositiveIntegerField(
        default=4096, validators=[MinValueValidator(256), MaxValueValidator(32000)]
    )
    effort = models.CharField(max_length=8, choices=Effort.choices, blank=True, default="")
    language = models.CharField(max_length=50, default="auto", help_text='"auto" replies in the customer\'s language.')
    welcome_message = models.TextField(blank=True)
    fallback_message = models.TextField(
        default="Sorry, I'm having trouble answering right now. A team member will get back to you shortly."
    )
    human_handoff_enabled = models.BooleanField(default=True)
    rag_enabled = models.BooleanField(default=True)
    memory_enabled = models.BooleanField(default=True)
    history_limit = models.PositiveSmallIntegerField(
        default=20, validators=[MinValueValidator(1), MaxValueValidator(100)]
    )

    def __str__(self):
        return f"{self.name} ({self.business})"
