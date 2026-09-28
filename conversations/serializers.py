from rest_framework import serializers

from customers.serializers import CustomerSerializer

from .models import Conversation, Message


class MessageSerializer(serializers.ModelSerializer):
    sender_email = serializers.EmailField(source="sender.email", read_only=True, default=None)

    class Meta:
        model = Message
        fields = [
            "id", "role", "direction", "message_type", "content", "status", "error",
            "sender_email", "metadata", "created_at",
        ]


class ConversationSerializer(serializers.ModelSerializer):
    customer = CustomerSerializer(read_only=True)
    assigned_agent_email = serializers.EmailField(source="assigned_agent.email", read_only=True, default=None)
    last_message = serializers.SerializerMethodField()

    class Meta:
        model = Conversation
        fields = [
            "id", "customer", "channel", "status", "assigned_agent_email", "handoff_reason",
            "started_at", "last_message_at", "resolved_at", "last_message",
        ]

    def get_last_message(self, obj):
        message = obj.messages.exclude(direction=Message.Direction.INTERNAL).order_by("-created_at", "-id").first()
        return MessageSerializer(message).data if message else None


class ReplySerializer(serializers.Serializer):
    content = serializers.CharField(max_length=4096)


class AssignSerializer(serializers.Serializer):
    user_id = serializers.IntegerField()
