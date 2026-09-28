from rest_framework import serializers

from accounts.models import User

from .models import AuditLog, Business, Membership, Role


class BusinessSerializer(serializers.ModelSerializer):
    class Meta:
        model = Business
        fields = ["id", "name", "slug", "email", "phone", "timezone", "status", "created_at"]
        read_only_fields = ["id", "slug", "status", "created_at"]


class MembershipSerializer(serializers.ModelSerializer):
    email = serializers.EmailField(source="user.email", read_only=True)
    full_name = serializers.CharField(source="user.full_name", read_only=True)

    class Meta:
        model = Membership
        fields = ["id", "email", "full_name", "role", "created_at"]
        read_only_fields = ["id", "email", "full_name", "created_at"]


class InviteMemberSerializer(serializers.Serializer):
    email = serializers.EmailField()
    role = serializers.ChoiceField(choices=[r for r in Role.values if r != Role.OWNER])

    def validate_email(self, value):
        try:
            return User.objects.get(email=value.lower())
        except User.DoesNotExist as exc:
            # A real invite flow would email a signup link; MVP requires an existing account.
            raise serializers.ValidationError("No user with this email; ask them to sign up first.") from exc


class AuditLogSerializer(serializers.ModelSerializer):
    actor_email = serializers.EmailField(source="actor.email", read_only=True, default=None)

    class Meta:
        model = AuditLog
        fields = ["id", "action", "actor_email", "target_type", "target_id", "metadata", "ip_address", "created_at"]
