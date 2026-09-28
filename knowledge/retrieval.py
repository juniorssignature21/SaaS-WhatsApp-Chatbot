"""Tenant-scoped similarity search over knowledge chunks."""

import json
import math
from dataclasses import dataclass

from django.conf import settings
from django.db import connection
from django.db.models.expressions import RawSQL

from .embeddings import get_embedder
from .models import KnowledgeChunk, KnowledgeDocument


@dataclass
class RetrievedChunk:
    chunk_id: int
    document_title: str
    content: str
    score: float


def _base_queryset(business, embedding_model):
    return KnowledgeChunk.objects.filter(
        business=business,
        embedding_model=embedding_model,
        document__enabled=True,
        document__status=KnowledgeDocument.Status.READY,
    ).select_related("document")


def _cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def search(business, query, top_k=None, min_score=0.05):
    """Return the ``top_k`` chunks of *this business* most similar to ``query``."""
    top_k = top_k or settings.KNOWLEDGE_TOP_K
    if not query.strip():
        return []
    embedder = get_embedder()
    query_vector = embedder.embed_query(query)
    qs = _base_queryset(business, embedder.model_name)

    if connection.vendor == "postgresql":
        # pgvector cosine distance, computed in the database.
        distance = RawSQL(
            f'"{KnowledgeChunk._meta.db_table}"."embedding" <=> %s::vector',
            (json.dumps(query_vector),),
        )
        rows = qs.annotate(distance=distance).order_by("distance")[:top_k]
        results = [
            RetrievedChunk(c.id, c.document.title, c.content, 1.0 - float(c.distance)) for c in rows
        ]
    else:
        scored = [
            RetrievedChunk(c.id, c.document.title, c.content, _cosine(query_vector, c.embedding))
            for c in qs if c.embedding
        ]
        results = sorted(scored, key=lambda r: r.score, reverse=True)[:top_k]
    return [r for r in results if r.score >= min_score]
