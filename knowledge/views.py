from dataclasses import asdict

from django.db import transaction
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from tenants.mixins import TenantModelViewSet
from tenants.models import Role
from tenants.services import audit

from . import retrieval
from .models import KnowledgeDocument
from .serializers import KnowledgeDocumentSerializer, KnowledgeDocumentUpdateSerializer, SearchSerializer
from .services import DocumentLimitReached, assert_can_add_document
from .tasks import process_knowledge_document


class KnowledgeDocumentViewSet(TenantModelViewSet):
    queryset = KnowledgeDocument.objects.none()
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    action_roles = {"search": Role.AGENT}

    def get_queryset(self):
        return KnowledgeDocument.objects.filter(business=self.business).order_by("-created_at")

    def get_serializer_class(self):
        if self.action in {"update", "partial_update"}:
            return KnowledgeDocumentUpdateSerializer
        return KnowledgeDocumentSerializer

    def perform_create(self, serializer):
        try:
            assert_can_add_document(self.business)
        except DocumentLimitReached as exc:
            raise PermissionDenied(str(exc)) from exc
        document = serializer.save(business=self.business)
        audit(self.business, self.actor, "knowledge.document_added", document, self.request)
        transaction.on_commit(lambda: process_knowledge_document.delay(document.id))

    def perform_destroy(self, instance):
        audit(self.business, self.actor, "knowledge.document_deleted", instance, self.request,
              title=instance.title)
        if instance.file:
            instance.file.delete(save=False)
        instance.delete()

    @action(detail=True, methods=["post"])
    def reprocess(self, request, pk=None):
        document = self.get_object()
        process_knowledge_document.delay(document.id)
        return Response({"status": "queued"}, status=202)

    @action(detail=False, methods=["post"])
    def search(self, request):
        """Preview what the bot would retrieve for a question."""
        serializer = SearchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        results = retrieval.search(
            self.business, serializer.validated_data["query"], serializer.validated_data.get("top_k")
        )
        return Response({"results": [asdict(r) for r in results]})
