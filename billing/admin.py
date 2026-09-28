from django.contrib import admin

from .models import Payment, Plan, Subscription, UsageRecord


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = ["code", "name", "price", "currency", "monthly_ai_responses", "is_public"]


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ["business", "plan", "status", "current_period_end"]
    list_filter = ["status", "plan"]


@admin.register(UsageRecord)
class UsageRecordAdmin(admin.ModelAdmin):
    list_display = [
        "business", "period", "conversations", "messages_in", "ai_responses", "input_tokens", "output_tokens",
    ]
    list_filter = ["period"]


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ["reference", "business", "plan", "amount", "currency", "status", "paid_at"]
    list_filter = ["status"]
    search_fields = ["reference"]
