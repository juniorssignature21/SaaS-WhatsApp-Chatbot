from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

from .context import acting_user, resolve_membership
from .permissions import IsBusinessMember


class TenantMixin:
    """Gives a view ``self.business`` / ``self.membership`` and tenant permissions."""

    permission_classes = [IsAuthenticated, IsBusinessMember]

    @property
    def membership(self):
        return resolve_membership(self.request)

    @property
    def business(self):
        return self.membership.business

    @property
    def actor(self):
        """The human performing the action (None for API-key requests)."""
        return acting_user(self.request)

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["business"] = self.business
        return context


class TenantModelViewSet(TenantMixin, viewsets.ModelViewSet):
    """ModelViewSet whose queryset and writes are always scoped to the tenant."""

    def get_queryset(self):
        return self.queryset.model.objects.filter(business=self.business)

    def perform_create(self, serializer):
        serializer.save(business=self.business)


class TenantReadOnlyViewSet(TenantMixin, viewsets.ReadOnlyModelViewSet):
    def get_queryset(self):
        return self.queryset.model.objects.filter(business=self.business)
