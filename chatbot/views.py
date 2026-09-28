from rest_framework import generics
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from tenants.mixins import TenantMixin
from tenants.services import audit

from .serializers import AIConfigurationSerializer, ApplyTemplateSerializer
from .templates import TEMPLATES, apply_template


class AIConfigurationView(TenantMixin, generics.RetrieveUpdateAPIView):
    serializer_class = AIConfigurationSerializer

    def get_object(self):
        return self.business.ai_config

    def perform_update(self, serializer):
        serializer.save()
        audit(self.business, self.request.user, "chatbot.settings_updated", serializer.instance, self.request,
              fields=sorted(serializer.validated_data))


class TemplateListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response([
            {"key": key, "name": t["name"], "bot_name": t["bot_name"], "prompt": t["prompt"],
             "suggested_tools": t["suggested_tools"]}
            for key, t in TEMPLATES.items()
        ])


class ApplyTemplateView(TenantMixin, APIView):
    def post(self, request):
        serializer = ApplyTemplateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        config = apply_template(self.business.ai_config, serializer.validated_data["template"])
        config.save()
        audit(self.business, request.user, "chatbot.template_applied", config, request, template=config.template)
        return Response(AIConfigurationSerializer(config).data)
