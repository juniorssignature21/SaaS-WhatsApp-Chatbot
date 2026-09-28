from django.conf import settings
from django.db import models

from common.models import TimeStampedModel


class Business(TimeStampedModel):
    """A tenant. Every tenant-owned row references exactly one Business."""

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE"
        SUSPENDED = "SUSPENDED"

    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=80, unique=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=32, blank=True)
    timezone = models.CharField(max_length=64, default="UTC")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)

    class Meta:
        verbose_name_plural = "businesses"

    def __str__(self):
        return self.name

    @property
    def is_active(self):
        return self.status == self.Status.ACTIVE


class Role(models.TextChoices):
    OWNER = "OWNER"
    ADMIN = "ADMIN"
    AGENT = "AGENT"
    VIEWER = "VIEWER"


ROLE_RANK = {Role.VIEWER: 0, Role.AGENT: 1, Role.ADMIN: 2, Role.OWNER: 3}


class Membership(TimeStampedModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memberships")
    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name="memberships")
    role = models.CharField(max_length=16, choices=Role.choices, default=Role.AGENT)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "business"], name="unique_membership")]

    def __str__(self):
        return f"{self.user} @ {self.business} ({self.role})"

    def has_role(self, minimum_role):
        return ROLE_RANK[self.role] >= ROLE_RANK[minimum_role]


class TenantQuerySet(models.QuerySet):
    def for_business(self, business):
        return self.filter(business=business)


class BusinessOwnedModel(TimeStampedModel):
    """Abstract base for every tenant-owned model."""

    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name="+")

    objects = TenantQuerySet.as_manager()

    class Meta:
        abstract = True


class AuditLog(models.Model):
    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name="audit_logs")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    action = models.CharField(max_length=100)
    target_type = models.CharField(max_length=100, blank=True)
    target_id = models.CharField(max_length=64, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["business", "-created_at"])]

    def __str__(self):
        return f"{self.action} by {self.actor_id} on {self.business_id}"
