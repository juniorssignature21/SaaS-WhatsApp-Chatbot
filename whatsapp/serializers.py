from rest_framework import serializers

from .models import MessageTemplate, WhatsAppAccount


class WhatsAppAccountSerializer(serializers.ModelSerializer):
    access_token = serializers.CharField(write_only=True, required=True, trim_whitespace=True)
    has_access_token = serializers.SerializerMethodField()

    class Meta:
        model = WhatsAppAccount
        fields = [
            "id", "display_name", "phone_number", "phone_number_id", "business_account_id",
            "access_token", "has_access_token", "status", "last_webhook_at", "created_at",
        ]
        read_only_fields = ["id", "last_webhook_at", "created_at"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance is not None:
            # Updating other fields must not require re-sending the secret.
            self.fields["access_token"].required = False

    def get_has_access_token(self, obj):
        return bool(obj.access_token)

    def validate_phone_number_id(self, value):
        qs = WhatsAppAccount.objects.filter(phone_number_id=value)
        if self.instance is not None:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("This phone number is already connected.")
        return value


class MessageTemplateSerializer(serializers.ModelSerializer):
    body_text = serializers.CharField(read_only=True)
    parameter_count = serializers.IntegerField(read_only=True)
    is_sendable = serializers.BooleanField(read_only=True)

    class Meta:
        model = MessageTemplate
        fields = ["id", "whatsapp_account", "name", "language", "category", "status", "body_text",
                  "parameter_count", "is_sendable"]
