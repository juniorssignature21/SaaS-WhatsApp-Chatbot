from django.contrib import admin

from .models import AIConfiguration


@admin.register(AIConfiguration)
class AIConfigurationAdmin(admin.ModelAdmin):
    list_display = ["business", "name", "model", "enabled", "rag_enabled", "human_handoff_enabled"]
    list_filter = ["enabled", "model"]
