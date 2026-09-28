from django.contrib import admin

from .models import AuditLog, Business, Membership


class MembershipInline(admin.TabularInline):
    model = Membership
    extra = 0
    autocomplete_fields = ["user"]


@admin.register(Business)
class BusinessAdmin(admin.ModelAdmin):
    list_display = ["name", "slug", "status", "created_at"]
    list_filter = ["status"]
    search_fields = ["name", "slug", "email"]
    inlines = [MembershipInline]


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ["created_at", "business", "actor", "action", "target_type", "target_id"]
    list_filter = ["action"]
    readonly_fields = [f.name for f in AuditLog._meta.fields]
