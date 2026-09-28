from rest_framework import generics
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from tenants.mixins import TenantMixin
from tenants.models import Role

from .models import Plan, UsageRecord
from .serializers import PlanSerializer, SubscriptionSerializer, UsageSerializer
from .services import get_usage


class PlanListView(generics.ListAPIView):
    serializer_class = PlanSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = None
    queryset = Plan.objects.filter(is_public=True).order_by("price")


class SubscriptionView(TenantMixin, APIView):
    read_role = Role.ADMIN

    def get(self, request):
        subscription = getattr(self.business, "subscription", None)
        return Response({
            "subscription": SubscriptionSerializer(subscription).data if subscription else None,
            "usage": UsageSerializer(get_usage(self.business)).data,
        })


class UsageHistoryView(TenantMixin, generics.ListAPIView):
    serializer_class = UsageSerializer
    read_role = Role.ADMIN

    def get_queryset(self):
        return UsageRecord.objects.filter(business=self.business)
