import os

from django.conf import settings
from rest_framework import serializers

from .loaders import SUPPORTED_EXTENSIONS
from .models import KnowledgeDocument


class FAQItemSerializer(serializers.Serializer):
    question = serializers.CharField(max_length=1000)
    answer = serializers.CharField(max_length=5000)


class KnowledgeDocumentSerializer(serializers.ModelSerializer):
    faqs = FAQItemSerializer(many=True, write_only=True, required=False)

    class Meta:
        model = KnowledgeDocument
        fields = [
            "id", "title", "source_type", "file", "source_url", "max_pages", "raw_text", "faqs",
            "status", "error", "chunk_count", "enabled", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "status", "error", "chunk_count", "created_at", "updated_at"]
        extra_kwargs = {"raw_text": {"required": False}, "file": {"required": False}}

    def validate_file(self, value):
        if value is None:
            return value
        ext = os.path.splitext(value.name)[1].lower()
        if ext not in SUPPORTED_EXTENSIONS:
            raise serializers.ValidationError(f"Supported types: {', '.join(sorted(SUPPORTED_EXTENSIONS))}.")
        if value.size > settings.KNOWLEDGE_MAX_UPLOAD_BYTES:
            raise serializers.ValidationError("File is too large.")
        return value

    def validate_max_pages(self, value):
        if not 1 <= value <= settings.KNOWLEDGE_MAX_CRAWL_PAGES:
            raise serializers.ValidationError(f"Between 1 and {settings.KNOWLEDGE_MAX_CRAWL_PAGES}.")
        return value

    def validate(self, attrs):
        if self.instance is not None:
            return attrs  # updates only toggle title/enabled
        Source = KnowledgeDocument.SourceType
        source = attrs.get("source_type")
        faqs = attrs.pop("faqs", None)
        if source == Source.FILE and not attrs.get("file"):
            raise serializers.ValidationError({"file": "A file is required."})
        if source == Source.URL and not attrs.get("source_url"):
            raise serializers.ValidationError({"source_url": "A URL is required."})
        if source == Source.FAQ:
            if not faqs:
                raise serializers.ValidationError({"faqs": "Provide at least one question/answer."})
            attrs["raw_text"] = "\n\n".join(f"Q: {f['question']}\nA: {f['answer']}" for f in faqs)
        if source == Source.TEXT and not attrs.get("raw_text", "").strip():
            raise serializers.ValidationError({"raw_text": "Text is required."})
        return attrs


class KnowledgeDocumentUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = KnowledgeDocument
        fields = ["title", "enabled"]


class SearchSerializer(serializers.Serializer):
    query = serializers.CharField(max_length=2000)
    top_k = serializers.IntegerField(min_value=1, max_value=20, required=False)
