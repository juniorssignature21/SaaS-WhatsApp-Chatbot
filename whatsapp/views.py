from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from tenants.mixins import TenantModelViewSet, TenantReadOnlyViewSet
from tenants.models import Role
from tenants.services import audit

from .client import WhatsAppAPIError, WhatsAppClient
from .models import MessageTemplate, WhatsAppAccount
from .serializers import MessageTemplateSerializer, WhatsAppAccountSerializer
from .services import ConnectNotAllowed, assert_can_connect, sync_templates


class WhatsAppAccountViewSet(TenantModelViewSet):
    serializer_class = WhatsAppAccountSerializer
    queryset = WhatsAppAccount.objects.none()

    def get_queryset(self):
        return WhatsAppAccount.objects.filter(business=self.business).order_by("created_at")

    def perform_create(self, serializer):
        try:
            assert_can_connect(self.business, self.actor)
        except ConnectNotAllowed as exc:
            raise PermissionDenied(str(exc)) from exc
        account = serializer.save(business=self.business)
        audit(self.business, self.actor, "whatsapp.connected", account, self.request,
              phone_number=account.phone_number)

    def perform_update(self, serializer):
        account = serializer.save()
        audit(self.business, self.actor, "whatsapp.updated", account, self.request,
              fields=sorted(k for k in serializer.validated_data if k != "access_token"),
              token_rotated="access_token" in serializer.validated_data)

    def perform_destroy(self, instance):
        audit(self.business, self.actor, "whatsapp.disconnected", instance, self.request,
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

    @action(detail=True, methods=["post"], url_path="sync-templates")
    def sync_templates(self, request, pk=None):
        account = self.get_object()
        try:
            count = sync_templates(account)
        except WhatsAppAPIError as exc:
            return Response({"ok": False, "error": str(exc)}, status=400)
        return Response({"ok": True, "synced": count})


class MessageTemplateViewSet(TenantReadOnlyViewSet):
    serializer_class = MessageTemplateSerializer
    queryset = MessageTemplate.objects.none()
    read_role = Role.AGENT
    pagination_class = None

    def get_queryset(self):
        qs = MessageTemplate.objects.filter(business=self.business)
        if self.request.query_params.get("sendable") == "true":
            qs = qs.filter(status="APPROVED")
        return qs
