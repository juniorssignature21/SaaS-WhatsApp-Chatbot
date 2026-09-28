from rest_framework import serializers

from .models import Payment, Plan, Subscription, UsageRecord


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
        fields = ["plan", "status", "trial_ends_at", "current_period_start", "current_period_end",
                  "cancel_at_period_end"]


class UsageSerializer(serializers.ModelSerializer):
    class Meta:
        model = UsageRecord
        fields = ["period", *UsageRecord.COUNTERS]


class PaymentSerializer(serializers.ModelSerializer):
    plan = serializers.CharField(source="plan.name", default=None)

    class Meta:
        model = Payment
        fields = ["reference", "plan", "amount", "currency", "status", "paid_at", "created_at"]
