from django.conf import settings
from django.db import models


class Notification(models.Model):
    class Kind(models.TextChoices):
        HANDOFF = "HANDOFF"
        SYSTEM = "SYSTEM"

    business = models.ForeignKey("tenants.Business", on_delete=models.CASCADE, related_name="notifications")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    kind = models.CharField(max_length=16, choices=Kind.choices, default=Kind.SYSTEM)
    title = models.CharField(max_length=200)
    body = models.TextField(blank=True)
    conversation = models.ForeignKey(
        "conversations.Conversation", null=True, blank=True, on_delete=models.CASCADE, related_name="+"
    )
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["user", "business", "read_at"])]

    def __str__(self):
        return self.title
