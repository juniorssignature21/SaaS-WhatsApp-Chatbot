import logging

from django.conf import settings
from django.db import transaction

from common.netsafety import UnsafeURLError

from .chunking import chunk_text
from .crawler import crawl
from .embeddings import EmbeddingError, get_embedder
from .loaders import LoaderError, load_file, load_url
from .models import KnowledgeChunk, KnowledgeDocument

logger = logging.getLogger(__name__)


class DocumentLimitReached(Exception):
    pass


def assert_can_add_document(business):
    from billing.services import check_limit

    count = KnowledgeDocument.objects.filter(business=business).count()
    if not check_limit(business, "max_knowledge_documents", count):
        raise DocumentLimitReached("Your plan's knowledge document limit has been reached. Upgrade to add more.")


def extract_text(document):
    Source = KnowledgeDocument.SourceType
    if document.source_type == Source.FILE:
        return load_file(document.file, document.file.name)
    if document.source_type == Source.URL:
        if document.max_pages > 1:
            return crawl(document.source_url, min(document.max_pages, settings.KNOWLEDGE_MAX_CRAWL_PAGES))
        return load_url(document.source_url)
    return document.raw_text


def process_document(document):
    """Extract -> clean -> chunk -> embed -> store. Replaces existing chunks."""
    KnowledgeDocument.objects.filter(pk=document.pk).update(status=KnowledgeDocument.Status.PROCESSING, error="")
    try:
        text = extract_text(document)
        chunks = chunk_text(text, settings.KNOWLEDGE_CHUNK_SIZE, settings.KNOWLEDGE_CHUNK_OVERLAP)
        if not chunks:
            raise LoaderError("No text could be extracted from this source.")
        embedder = get_embedder()
        vectors = embedder.embed_documents(chunks)
    except (LoaderError, EmbeddingError, UnsafeURLError, ValueError) as exc:
        logger.info("Knowledge document %s failed: %s", document.pk, exc)
        KnowledgeDocument.objects.filter(pk=document.pk).update(
            status=KnowledgeDocument.Status.FAILED, error=str(exc)[:2000]
        )
        return False

    with transaction.atomic():
        KnowledgeChunk.objects.filter(document=document).delete()
        KnowledgeChunk.objects.bulk_create([
            KnowledgeChunk(
                business_id=document.business_id, document=document, index=i,
                content=content, embedding=vector, embedding_model=embedder.model_name,
            )
            for i, (content, vector) in enumerate(zip(chunks, vectors, strict=True))
        ])
        update = {"status": KnowledgeDocument.Status.READY, "chunk_count": len(chunks), "error": ""}
        if document.source_type in {KnowledgeDocument.SourceType.FILE, KnowledgeDocument.SourceType.URL}:
            update["raw_text"] = text
        KnowledgeDocument.objects.filter(pk=document.pk).update(**update)
    return True
