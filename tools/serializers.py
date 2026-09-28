from rest_framework import serializers

from .builtins import BUILTIN_NAMES
from .models import Tool


class ToolSerializer(serializers.ModelSerializer):
    signing_secret = serializers.CharField(read_only=True)

    class Meta:
        model = Tool
        fields = [
            "id", "name", "description", "input_schema", "endpoint_url", "http_method",
            "timeout_seconds", "enabled", "signing_secret", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate_name(self, value):
        if value in BUILTIN_NAMES:
            raise serializers.ValidationError("This name is reserved for a built-in tool.")
        business = self.context["business"]
        qs = Tool.objects.filter(business=business, name=value)
        if self.instance is not None:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("A tool with this name already exists.")
        return value

    def validate_input_schema(self, value):
        if value and (not isinstance(value, dict) or value.get("type") != "object"):
            raise serializers.ValidationError('The schema must be a JSON Schema with "type": "object".')
        return value

    def validate_timeout_seconds(self, value):
        if not 1 <= value <= 30:
            raise serializers.ValidationError("Timeout must be between 1 and 30 seconds.")
        return value
