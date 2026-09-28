from rest_framework import generics, mixins, status, viewsets
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from .mixins import TenantMixin
from .models import APIKey, AuditLog, Business, Membership, Role
from .permissions import IsHumanUser
from .serializers import (
    APIKeySerializer,
    AuditLogSerializer,
    BusinessSerializer,
    InviteMemberSerializer,
    MembershipSerializer,
)
from .services import audit, create_business


class MyBusinessesView(generics.ListCreateAPIView):
    """Businesses the current user belongs to; POST creates another one."""

    serializer_class = BusinessSerializer
    permission_classes = [IsHumanUser]

    def get_queryset(self):
        return Business.objects.filter(memberships__user=self.request.user).order_by("name")

    def perform_create(self, serializer):
        data = dict(serializer.validated_data)
        serializer.instance = create_business(owner=self.request.user, name=data.pop("name"), **data)


class CurrentBusinessView(TenantMixin, generics.RetrieveUpdateAPIView):
    serializer_class = BusinessSerializer

    def get_object(self):
        return self.business

    def perform_update(self, serializer):
        serializer.save()
        audit(self.business, self.actor, "business.updated", self.business, self.request,
              fields=sorted(serializer.validated_data))


class TeamViewSet(TenantMixin, mixins.ListModelMixin, mixins.UpdateModelMixin,
                  mixins.DestroyModelMixin, viewsets.GenericViewSet):
    serializer_class = MembershipSerializer
    queryset = Membership.objects.none()

    def get_queryset(self):
        return Membership.objects.filter(business=self.business).select_related("user").order_by("created_at")

    def create(self, request):
        serializer = InviteMemberSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data["email"]
        role = serializer.validated_data["role"]
        self._check_can_grant(role)
        membership, created = Membership.objects.get_or_create(
            user=user, business=self.business, defaults={"role": role}
        )
        if not created:
            raise ValidationError({"email": "This user is already a member."})
        audit(self.business, self.actor, "team.member_added", membership, request, role=role)
        return Response(MembershipSerializer(membership).data, status=status.HTTP_201_CREATED)

    def perform_update(self, serializer):
        target = serializer.instance
        new_role = serializer.validated_data.get("role", target.role)
        if target.role == Role.OWNER or new_role == Role.OWNER:
            raise PermissionDenied("Ownership cannot be changed through this endpoint.")
        self._check_can_grant(new_role)
        serializer.save()
        audit(self.business, self.actor, "team.role_changed", target, self.request, role=new_role)

    def perform_destroy(self, instance):
        if instance.role == Role.OWNER:
            raise PermissionDenied("The owner cannot be removed.")
        self._check_can_grant(instance.role)
        audit(self.business, self.actor, "team.member_removed", instance, self.request,
              email=instance.user.email)
        instance.delete()

    def _check_can_grant(self, role):
        # Only owners may create or modify admins.
        if role == Role.ADMIN and not self.membership.has_role(Role.OWNER):
            raise PermissionDenied("Only the owner can manage admins.")


class AuditLogView(TenantMixin, generics.ListAPIView):
    serializer_class = AuditLogSerializer
    read_role = Role.ADMIN

    def get_queryset(self):
        return AuditLog.objects.filter(business=self.business).select_related("actor")


class APIKeyViewSet(TenantMixin, mixins.ListModelMixin, mixins.CreateModelMixin, mixins.DestroyModelMixin,
                    viewsets.GenericViewSet):
    """Create (key shown once), list and revoke API keys. Owner/admin only."""

    serializer_class = APIKeySerializer
    queryset = APIKey.objects.none()
    read_role = Role.ADMIN
    permission_classes = [IsHumanUser, *TenantMixin.permission_classes[1:]]

    def get_queryset(self):
        return APIKey.objects.filter(business=self.business, revoked_at__isnull=True)

    def create(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        key, raw = APIKey.issue(self.business, created_by=self.actor, **serializer.validated_data)
        audit(self.business, self.actor, "api_key.created", key, request, name=key.name, role=key.role)
        return Response({**APIKeySerializer(key).data, "key": raw}, status=status.HTTP_201_CREATED)

    def perform_destroy(self, instance):
        instance.revoke()
        audit(self.business, self.actor, "api_key.revoked", instance, self.request, name=instance.name)
