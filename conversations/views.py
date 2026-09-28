from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from tenants.mixins import TenantMixin
from tenants.models import Membership, Role

from . import services
from .models import Conversation
from .serializers import AssignSerializer, ConversationSerializer, MessageSerializer, ReplySerializer


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
            qs = qs.filter(assigned_agent=self.request.user)
        return qs.order_by("-last_message_at")

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
        message = services.agent_reply(conversation, serializer.validated_data["content"], request.user)
        return Response(MessageSerializer(message).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def takeover(self, request, pk=None):
        conversation = services.handoff_to_human(
            self.get_object(), reason=f"Taken over by {request.user.email}.", actor=request.user
        )
        return Response(self.get_serializer(conversation).data)

    @action(detail=True, methods=["post"], url_path="return-to-ai")
    def return_to_ai(self, request, pk=None):
        conversation = services.return_to_ai(self.get_object(), actor=request.user)
        return Response(self.get_serializer(conversation).data)

    @action(detail=True, methods=["post"])
    def resolve(self, request, pk=None):
        conversation = services.resolve(self.get_object(), actor=request.user)
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
