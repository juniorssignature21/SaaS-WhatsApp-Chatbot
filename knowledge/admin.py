from django.contrib import admin

from .models import KnowledgeDocument


@admin.register(KnowledgeDocument)
class KnowledgeDocumentAdmin(admin.ModelAdmin):
    list_display = ["title", "business", "source_type", "status", "chunk_count", "enabled", "created_at"]
    list_filter = ["status", "source_type"]
    search_fields = ["title"]
