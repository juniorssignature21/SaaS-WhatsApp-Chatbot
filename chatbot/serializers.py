from rest_framework import serializers

from .models import AIConfiguration
from .templates import TEMPLATES


class AIConfigurationSerializer(serializers.ModelSerializer):
    class Meta:
        model = AIConfiguration
        fields = [
            "enabled", "template", "name", "system_prompt", "model", "max_tokens", "effort", "language",
            "welcome_message", "fallback_message", "human_handoff_enabled", "rag_enabled",
            "memory_enabled", "history_limit", "updated_at",
        ]
        read_only_fields = ["template", "updated_at"]

    def validate_model(self, value):
        if not value.startswith("claude-"):
            raise serializers.ValidationError("Unsupported model.")
        return value


class ApplyTemplateSerializer(serializers.Serializer):
    template = serializers.ChoiceField(choices=sorted(TEMPLATES))

