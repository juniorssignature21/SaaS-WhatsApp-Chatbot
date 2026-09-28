from rest_framework import generics, serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from conversations.serializers import MessageSerializer
from tenants.mixins import TenantMixin
from tenants.models import Role
from tenants.services import audit

from . import playground
from .llm import LLMError
from .serializers import AIConfigurationSerializer, ApplyTemplateSerializer
from .templates import TEMPLATES, apply_template


class AIConfigurationView(TenantMixin, generics.RetrieveUpdateAPIView):
    serializer_class = AIConfigurationSerializer

    def get_object(self):
        return self.business.ai_config

    def perform_update(self, serializer):
        serializer.save()
        audit(self.business, self.actor, "chatbot.settings_updated", serializer.instance, self.request,
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
        audit(self.business, self.actor, "chatbot.template_applied", config, request, template=config.template)
        return Response(AIConfigurationSerializer(config).data)


class PlaygroundSerializer(serializers.Serializer):
    message = serializers.CharField(max_length=4000, required=False, allow_blank=True)
    reset = serializers.BooleanField(default=False)


class PlaygroundView(TenantMixin, APIView):
    """Chat with the configured bot without WhatsApp. Uses real LLM calls (and usage)."""

    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "playground"
    write_role = Role.AGENT

    def _key(self):
        return str(self.actor.pk) if self.actor else f"key-{self.request.auth.pk}"

    def get(self, request):
        conversation = playground.playground_conversation(self.business, self._key())
        messages = conversation.messages.exclude(role="TOOL").order_by("id")
        return Response({"messages": MessageSerializer(messages, many=True).data})

    def post(self, request):
        serializer = PlaygroundSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if serializer.validated_data["reset"]:
            playground.reset(self.business, self._key())
            return Response({"messages": []})
        text = serializer.validated_data.get("message", "").strip()
        if not text:
            return Response({"detail": "Type a message."}, status=400)
        try:
            conversation, outcome = playground.chat(self.business, self._key(), text)
        except LLMError as exc:
            return Response({"detail": f"The AI provider failed: {exc}"}, status=502)
        messages = conversation.messages.exclude(role="TOOL").order_by("id")
        return Response({
            "outcome": outcome.action, "reason": outcome.reason,
            "messages": MessageSerializer(messages, many=True).data,
        })
