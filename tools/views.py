from rest_framework.decorators import action
from rest_framework.response import Response

from tenants.mixins import TenantModelViewSet
from tenants.models import Role
from tenants.services import audit

from .models import Tool, generate_signing_secret
from .serializers import ToolSerializer


class ToolViewSet(TenantModelViewSet):
    serializer_class = ToolSerializer
    queryset = Tool.objects.none()
    read_role = Role.ADMIN  # responses include the signing secret

    def get_queryset(self):
        return Tool.objects.filter(business=self.business).order_by("name")

    def perform_create(self, serializer):
        tool = serializer.save(business=self.business)
        audit(self.business, self.request.user, "tool.created", tool, self.request, name=tool.name)

    def perform_update(self, serializer):
        tool = serializer.save()
        audit(self.business, self.request.user, "tool.updated", tool, self.request, name=tool.name)

    def perform_destroy(self, instance):
        audit(self.business, self.request.user, "tool.deleted", instance, self.request, name=instance.name)
        instance.delete()

    @action(detail=True, methods=["post"], url_path="rotate-secret")
    def rotate_secret(self, request, pk=None):
        tool = self.get_object()
        tool.signing_secret = generate_signing_secret()
        tool.save(update_fields=["signing_secret", "updated_at"])
        audit(self.business, request.user, "tool.secret_rotated", tool, request)
        return Response(ToolSerializer(tool, context=self.get_serializer_context()).data)
