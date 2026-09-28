from rest_framework import serializers

from .models import Customer


class CustomerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Customer
        fields = ["id", "phone_number", "name", "email", "external_id", "metadata", "created_at", "updated_at"]
        read_only_fields = ["id", "phone_number", "created_at", "updated_at"]
