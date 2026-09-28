from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from billing.services import check_limit
from tenants.mixins import TenantModelViewSet
from tenants.services import audit

from .client import WhatsAppAPIError, WhatsAppClient
from .models import WhatsAppAccount
from .serializers import WhatsAppAccountSerializer


class WhatsAppAccountViewSet(TenantModelViewSet):
    serializer_class = WhatsAppAccountSerializer
    queryset = WhatsAppAccount.objects.none()

    def get_queryset(self):
        return WhatsAppAccount.objects.filter(business=self.business).order_by("created_at")

    def perform_create(self, serializer):
        count = WhatsAppAccount.objects.filter(business=self.business).count()
        if not check_limit(self.business, "max_whatsapp_numbers", count):
            raise PermissionDenied("Your plan's WhatsApp number limit has been reached.")
        account = serializer.save(business=self.business)
        audit(self.business, self.request.user, "whatsapp.connected", account, self.request,
              phone_number=account.phone_number)

    def perform_update(self, serializer):
        account = serializer.save()
        audit(self.business, self.request.user, "whatsapp.updated", account, self.request,
              fields=sorted(k for k in serializer.validated_data if k != "access_token"),
              token_rotated="access_token" in serializer.validated_data)

    def perform_destroy(self, instance):
        audit(self.business, self.request.user, "whatsapp.disconnected", instance, self.request,
              phone_number=instance.phone_number)
        instance.delete()

    @action(detail=True, methods=["post"])
    def verify(self, request, pk=None):
        """Check the stored credentials against the Graph API."""
        account = self.get_object()
        try:
            info = WhatsAppClient(account).get_phone_number_info()
        except WhatsAppAPIError as exc:
            return Response({"ok": False, "error": str(exc)}, status=400)
        return Response({"ok": True, "info": info})
