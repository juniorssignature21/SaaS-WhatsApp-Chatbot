import os
import uuid

from django.db import models

from common.fields import EmbeddingField
from tenants.models import BusinessOwnedModel


def document_upload_path(instance, filename):
    # Tenant-prefixed, unguessable path; the original name is kept in `title`.
    ext = os.path.splitext(filename)[1].lower()[:10]
    return f"knowledge/{instance.business_id}/{uuid.uuid4().hex}{ext}"


class KnowledgeDocument(BusinessOwnedModel):
    class SourceType(models.TextChoices):
        FILE = "FILE"
        TEXT = "TEXT"
        URL = "URL"
        FAQ = "FAQ"

    class Status(models.TextChoices):
        PENDING = "PENDING"
        PROCESSING = "PROCESSING"
        READY = "READY"
        FAILED = "FAILED"

    title = models.CharField(max_length=255)
    source_type = models.CharField(max_length=8, choices=SourceType.choices)
    file = models.FileField(upload_to=document_upload_path, blank=True)
    source_url = models.URLField(blank=True)
    max_pages = models.PositiveSmallIntegerField(
        default=1, help_text="For URLs: crawl up to this many pages on the same site (1 = just this page)."
    )
    raw_text = models.TextField(blank=True, help_text="Pasted text / FAQ, or the extracted text.")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    error = models.TextField(blank=True)
    chunk_count = models.PositiveIntegerField(default=0)
    enabled = models.BooleanField(default=True)

    def __str__(self):
        return self.title


class KnowledgeChunk(models.Model):
    business = models.ForeignKey("tenants.Business", on_delete=models.CASCADE, related_name="+")
    document = models.ForeignKey(KnowledgeDocument, on_delete=models.CASCADE, related_name="chunks")
    index = models.PositiveIntegerField()
    content = models.TextField()
    embedding = EmbeddingField(null=True)
    embedding_model = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["document_id", "index"]
        indexes = [models.Index(fields=["business", "document"])]

    def __str__(self):
        return f"{self.document_id}#{self.index}"
