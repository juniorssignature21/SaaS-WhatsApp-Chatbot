from django.utils import timezone
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from tenants.mixins import TenantMixin
from tenants.models import Role
from tenants.permissions import IsBusinessMember, IsHumanUser

from .models import Notification
from .serializers import NotificationSerializer


class NotificationViewSet(TenantMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    serializer_class = NotificationSerializer
    queryset = Notification.objects.none()
    permission_classes = [IsHumanUser, IsBusinessMember]
    write_role = Role.VIEWER

    def get_queryset(self):
        qs = Notification.objects.filter(user=self.request.user, business=self.business)
        if self.request.query_params.get("unread") == "true":
            qs = qs.filter(read_at__isnull=True)
        return qs

    @action(detail=True, methods=["post"])
    def read(self, request, pk=None):
        self.get_queryset().filter(pk=pk).update(read_at=timezone.now())
        return Response(status=204)

    @action(detail=False, methods=["post"], url_path="read-all")
    def read_all(self, request):
        self.get_queryset().filter(read_at__isnull=True).update(read_at=timezone.now())
        return Response(status=204)
