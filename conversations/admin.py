from django.contrib import admin

from .models import Conversation, Message


class MessageInline(admin.TabularInline):
    model = Message
    extra = 0
    fields = ["created_at", "role", "direction", "content", "status"]
    readonly_fields = fields


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ["id", "business", "customer", "status", "assigned_agent", "last_message_at"]
    list_filter = ["status", "channel", "business"]
    inlines = [MessageInline]


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ["id", "business", "conversation", "role", "direction", "status", "created_at"]
    list_filter = ["role", "direction", "status"]
    search_fields = ["content", "external_id"]
