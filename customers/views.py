from django.db.models import Q
from rest_framework import mixins, viewsets

from tenants.mixins import TenantMixin
from tenants.models import Role

from .models import Customer
from .serializers import CustomerSerializer


class CustomerViewSet(TenantMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin,
                      mixins.UpdateModelMixin, viewsets.GenericViewSet):
    serializer_class = CustomerSerializer
    queryset = Customer.objects.none()
    write_role = Role.AGENT

    def get_queryset(self):
        qs = (Customer.objects.filter(business=self.business).exclude(phone_number__startswith="sandbox-")
              .order_by("-updated_at"))
        search = self.request.query_params.get("search")
        if search:
            qs = qs.filter(Q(name__icontains=search) | Q(phone_number__icontains=search) | Q(email__icontains=search))
        return qs
