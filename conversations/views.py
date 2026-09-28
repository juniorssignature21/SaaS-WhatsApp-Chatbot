from django.http import FileResponse, Http404
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from tenants.mixins import TenantMixin
from tenants.models import Membership, Role
from whatsapp.models import MessageTemplate, WhatsAppAccount

from . import services
from .models import Conversation, Message
from .serializers import (
    AssignSerializer,
    ConversationSerializer,
    MessageSerializer,
    ReplySerializer,
    SendTemplateSerializer,
    StartConversationSerializer,
)


class ConversationViewSet(TenantMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = ConversationSerializer
    queryset = Conversation.objects.none()
    write_role = Role.AGENT

    def get_queryset(self):
        qs = Conversation.objects.filter(business=self.business).select_related("customer", "assigned_agent")
        params = self.request.query_params
        if params.get("status"):
            qs = qs.filter(status__in=params["status"].split(","))
        if params.get("customer"):
            qs = qs.filter(customer_id=params["customer"])
        if params.get("mine") == "true":
            qs = qs.filter(assigned_agent=self.actor) if self.actor else qs.none()
        if params.get("include_sandbox") != "true":
            qs = qs.exclude(channel="SANDBOX")
        return qs.order_by("-last_message_at")

    def _template(self, template_id):
        template = MessageTemplate.objects.filter(business=self.business, pk=template_id).first()
        if template is None:
            raise ValidationError({"template_id": "Unknown template."})
        return template

    @action(detail=True, methods=["get"])
    def messages(self, request, pk=None):
        conversation = self.get_object()
        page = self.paginate_queryset(conversation.messages.select_related("sender").all())
        return self.get_paginated_response(MessageSerializer(page, many=True).data)

    @action(detail=True, methods=["post"])
    def reply(self, request, pk=None):
        conversation = self.get_object()
        serializer = ReplySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            message = services.agent_reply(conversation, serializer.validated_data["content"], self.actor)
        except services.ServiceWindowClosed as exc:
            return Response({"detail": str(exc), "code": "service_window_closed"}, status=status.HTTP_409_CONFLICT)
        return Response(MessageSerializer(message).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="send-template")
    def send_template(self, request, pk=None):
        conversation = self.get_object()
        serializer = SendTemplateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            message = services.send_template_message(
                conversation, self._template(data["template_id"]), data.get("params", []), sender=self.actor
            )
        except ValueError as exc:
            raise ValidationError({"detail": str(exc)}) from exc
        return Response(MessageSerializer(message).data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["post"])
    def start(self, request):
        """Message a customer first, using an approved template."""
        serializer = StartConversationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        account = WhatsAppAccount.objects.filter(business=self.business, pk=data["whatsapp_account_id"]).first()
        if account is None:
            raise ValidationError({"whatsapp_account_id": "Unknown WhatsApp number."})
        try:
            message = services.start_conversation(
                self.business, account, data["phone_number"], self._template(data["template_id"]),
                data.get("params", []), sender=self.actor, name=data.get("name", ""),
            )
        except ValueError as exc:
            raise ValidationError({"detail": str(exc)}) from exc
        return Response(self.get_serializer(message.conversation).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def takeover(self, request, pk=None):
        actor = self.actor
        who = actor.email if actor else "the API"
        conversation = services.handoff_to_human(self.get_object(), reason=f"Taken over by {who}.", actor=actor)
        return Response(self.get_serializer(conversation).data)

    @action(detail=True, methods=["post"], url_path="return-to-ai")
    def return_to_ai(self, request, pk=None):
        conversation = services.return_to_ai(self.get_object(), actor=self.actor)
        return Response(self.get_serializer(conversation).data)

    @action(detail=True, methods=["post"])
    def resolve(self, request, pk=None):
        conversation = services.resolve(self.get_object(), actor=self.actor)
        return Response(self.get_serializer(conversation).data)

    @action(detail=True, methods=["post"])
    def assign(self, request, pk=None):
        conversation = self.get_object()
        serializer = AssignSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        membership = Membership.objects.filter(
            business=self.business, user_id=serializer.validated_data["user_id"]
        ).select_related("user").first()
        if membership is None or not membership.has_role(Role.AGENT):
            raise ValidationError({"user_id": "Not an agent of this business."})
        conversation.assigned_agent = membership.user
        conversation.save(update_fields=["assigned_agent", "updated_at"])
        return Response(self.get_serializer(conversation).data)


class MessageMediaViewSet(TenantMixin, viewsets.GenericViewSet):
    """Authenticated download of message attachments (never served publicly)."""

    queryset = Message.objects.none()

    def retrieve(self, request, pk=None):
        message = Message.objects.filter(business=self.business, pk=pk).first()
        if message is None or not message.media:
            raise Http404
        return FileResponse(message.media.open("rb"), content_type=message.media_mime_type or None,
                            as_attachment=False)
