from django.contrib import admin

from .models import WhatsAppAccount


@admin.register(WhatsAppAccount)
class WhatsAppAccountAdmin(admin.ModelAdmin):
    list_display = ["phone_number", "display_name", "business", "status", "last_webhook_at"]
    list_filter = ["status"]
    search_fields = ["phone_number", "phone_number_id"]
    exclude = ["access_token"]
