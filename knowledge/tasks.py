from celery import shared_task

from .models import KnowledgeDocument
from .services import process_document


@shared_task
def process_knowledge_document(document_id):
    document = KnowledgeDocument.objects.filter(pk=document_id).first()
    if document is not None:
        process_document(document)
