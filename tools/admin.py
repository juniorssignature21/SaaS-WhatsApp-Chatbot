from django.contrib import admin

from .models import Tool


@admin.register(Tool)
class ToolAdmin(admin.ModelAdmin):
    list_display = ["name", "business", "endpoint_url", "enabled"]
    list_filter = ["enabled"]
    exclude = ["signing_secret"]
