from rest_framework import serializers

from .models import Plan, Subscription, UsageRecord


class PlanSerializer(serializers.ModelSerializer):
    class Meta:
        model = Plan
        fields = [
            "code", "name", "price", "currency", "max_whatsapp_numbers", "max_team_members",
            "max_knowledge_documents", "monthly_conversations", "monthly_ai_responses", "features",
        ]


class SubscriptionSerializer(serializers.ModelSerializer):
    plan = PlanSerializer(read_only=True)

    class Meta:
        model = Subscription
        fields = ["plan", "status", "current_period_start", "current_period_end"]


class UsageSerializer(serializers.ModelSerializer):
    class Meta:
        model = UsageRecord
        fields = ["period", *UsageRecord.COUNTERS]
