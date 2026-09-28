import hashlib
import secrets

from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models
from django.utils import timezone

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
    # White-labeling for the dashboard.
    brand_name = models.CharField(max_length=100, blank=True)
    brand_color = models.CharField(
        max_length=7, blank=True, validators=[RegexValidator(r"^#[0-9a-fA-F]{6}$", "Use a hex colour like #0f9d58.")]
    )

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
    notify_by_email = models.BooleanField(default=True, help_text="Email me when a conversation needs a human.")

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


class APIKey(models.Model):
    """Server-to-server credential for a business's own systems.

    The full key is shown once at creation; only its SHA-256 hash is stored.
    Format: ``wak_<prefix>_<secret>``; send as ``Authorization: Api-Key <key>``.
    """

    ROLE_CHOICES = [(Role.ADMIN, "Admin"), (Role.AGENT, "Agent"), (Role.VIEWER, "Viewer")]

    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name="api_keys")
    name = models.CharField(max_length=100)
    prefix = models.CharField(max_length=16, unique=True)
    key_hash = models.CharField(max_length=64)
    role = models.CharField(max_length=16, choices=ROLE_CHOICES, default=Role.AGENT)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} ({self.prefix})"

    @staticmethod
    def hash(raw_key):
        return hashlib.sha256(raw_key.encode()).hexdigest()

    @classmethod
    def issue(cls, business, name, role=Role.AGENT, created_by=None):
        prefix = secrets.token_hex(4)
        raw = f"wak_{prefix}_{secrets.token_urlsafe(32)}"
        key = cls.objects.create(
            business=business, name=name, prefix=prefix, key_hash=cls.hash(raw), role=role, created_by=created_by
        )
        return key, raw

    @property
    def is_active(self):
        return self.revoked_at is None

    def revoke(self):
        self.revoked_at = timezone.now()
        self.save(update_fields=["revoked_at"])
