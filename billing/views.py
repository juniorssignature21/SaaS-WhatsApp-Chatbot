from django.conf import settings
from django.urls import reverse
from rest_framework import generics, serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from tenants.mixins import TenantMixin
from tenants.models import Role

from . import paystack
from .models import Payment, Plan, UsageRecord
from .serializers import PaymentSerializer, PlanSerializer, SubscriptionSerializer, UsageSerializer
from .services import cancel_subscription, confirm_payment, get_usage, start_checkout


class PlanListView(generics.ListAPIView):
    serializer_class = PlanSerializer
    permission_classes = [IsAuthenticated]  # API keys may read public plans
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


class CheckoutSerializer(serializers.Serializer):
    plan = serializers.SlugField()


class CheckoutView(TenantMixin, APIView):
    """Start a Paystack checkout for a plan; redirect the user to ``authorization_url``."""

    write_role = Role.OWNER

    def post(self, request):
        serializer = CheckoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        plan = Plan.objects.filter(code=serializer.validated_data["plan"], is_public=True).first()
        if plan is None:
            return Response({"plan": ["Unknown plan."]}, status=400)
        email = self.actor.email if self.actor else self.business.email
        callback = settings.SITE_URL + reverse("dashboard:billing_callback")
        try:
            url, payment = start_checkout(self.business, plan, email, callback)
        except paystack.PaystackError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        return Response({"authorization_url": url, "reference": payment.reference})


class VerifyPaymentView(TenantMixin, APIView):
    write_role = Role.OWNER

    def post(self, request):
        reference = str(request.data.get("reference", ""))
        if not Payment.objects.filter(business=self.business, reference=reference).exists():
            return Response({"reference": ["Unknown payment."]}, status=400)
        try:
            payment = confirm_payment(reference)
        except paystack.PaystackError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        return Response(PaymentSerializer(payment).data)


class CancelSubscriptionView(TenantMixin, APIView):
    write_role = Role.OWNER

    def post(self, request):
        try:
            subscription = cancel_subscription(self.business)
        except paystack.PaystackError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        return Response(SubscriptionSerializer(subscription).data)


class PaymentListView(TenantMixin, generics.ListAPIView):
    serializer_class = PaymentSerializer
    read_role = Role.ADMIN

    def get_queryset(self):
        return Payment.objects.filter(business=self.business).select_related("plan")
