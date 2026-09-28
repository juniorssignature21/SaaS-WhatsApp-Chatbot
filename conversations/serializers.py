from rest_framework import serializers

from customers.serializers import CustomerSerializer

from .models import Conversation, Message


class MessageSerializer(serializers.ModelSerializer):
    sender_email = serializers.EmailField(source="sender.email", read_only=True, default=None)
    media_url = serializers.SerializerMethodField()

    class Meta:
        model = Message
        fields = [
            "id", "role", "direction", "message_type", "content", "status", "error",
            "sender_email", "media_url", "media_mime_type", "metadata", "created_at",
        ]

    def get_media_url(self, obj):
        return f"/api/v1/message-media/{obj.id}/" if obj.media else None


class ConversationSerializer(serializers.ModelSerializer):
    customer = CustomerSerializer(read_only=True)
    assigned_agent_email = serializers.EmailField(source="assigned_agent.email", read_only=True, default=None)
    last_message = serializers.SerializerMethodField()

    class Meta:
        model = Conversation
        fields = [
            "id", "customer", "channel", "status", "assigned_agent_email", "handoff_reason",
            "started_at", "last_message_at", "resolved_at", "last_message", "service_window_open",
        ]

    def get_last_message(self, obj):
        message = obj.messages.exclude(direction=Message.Direction.INTERNAL).order_by("-created_at", "-id").first()
        return MessageSerializer(message).data if message else None


class ReplySerializer(serializers.Serializer):
    content = serializers.CharField(max_length=4096)


class AssignSerializer(serializers.Serializer):
    user_id = serializers.IntegerField()


class SendTemplateSerializer(serializers.Serializer):
    template_id = serializers.IntegerField()
    params = serializers.ListField(child=serializers.CharField(max_length=1000), required=False, max_length=20)


class StartConversationSerializer(SendTemplateSerializer):
    whatsapp_account_id = serializers.IntegerField()
    phone_number = serializers.RegexField(r"^\+?\d{7,15}$", error_messages={"invalid": "Use international format."})
    name = serializers.CharField(max_length=200, required=False, allow_blank=True)

    def validate_phone_number(self, value):
        return value.lstrip("+")
