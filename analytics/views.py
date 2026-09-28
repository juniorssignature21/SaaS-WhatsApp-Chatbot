from datetime import timedelta

from django.db.models import Avg, Count, DurationField, ExpressionWrapper, F, Min, OuterRef, Subquery
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from billing.services import get_usage
from conversations.models import Conversation, Message
from tenants.mixins import TenantMixin


class OverviewView(TenantMixin, APIView):
    """Dashboard numbers for the current month plus live conversation counts."""

    def get(self, request):
        business = self.business
        usage = get_usage(business)
        by_status = dict(
            Conversation.objects.filter(business=business)
            .values_list("status").annotate(n=Count("id")).values_list("status", "n")
        )
        return Response({
            "period": usage.period,
            "conversations": {
                "this_month": usage.conversations,
                "resolved_this_month": usage.resolved_conversations,
                "escalations_this_month": usage.escalations,
                "by_status": by_status,
            },
            "messages": {
                "received": usage.messages_in,
                "sent": usage.messages_out,
                "ai_responses": usage.ai_responses,
                "human_responses": usage.human_responses,
            },
            "ai": {
                "tool_calls": usage.tool_calls,
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "cache_read_tokens": usage.cache_read_tokens,
            },
            "avg_first_response_seconds": self._avg_first_response(business),
        })

    @staticmethod
    def _avg_first_response(business, days=30):
        """Average time from a conversation's first customer message to its first reply."""
        since = timezone.now() - timedelta(days=days)
        first_reply = (
            Message.objects.filter(
                conversation=OuterRef("pk"), direction=Message.Direction.OUTBOUND,
            ).order_by("created_at").values("created_at")[:1]
        )
        qs = (
            Conversation.objects.filter(business=business, started_at__gte=since)
            .annotate(
                first_in=Min("messages__created_at"),
                first_out=Subquery(first_reply),
            )
            .filter(first_out__isnull=False)
            .annotate(delay=ExpressionWrapper(F("first_out") - F("first_in"), output_field=DurationField()))
        )
        result = qs.aggregate(avg=Avg("delay"))["avg"]
        return round(result.total_seconds(), 1) if result else None
