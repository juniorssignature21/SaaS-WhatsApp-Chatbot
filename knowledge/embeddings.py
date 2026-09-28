"""Embedding providers.

``hashing`` is a local, dependency-free feature-hashing embedder: good enough
for development, tests and small FAQ sets. Use ``voyage`` (or add another
provider here) for production-quality semantic search.
"""

import hashlib
import math
import re

import requests
from django.conf import settings

TOKEN_RE = re.compile(r"\w+", re.UNICODE)


class EmbeddingError(Exception):
    pass


class HashingEmbedder:
    def __init__(self, dimensions=None):
        self.dimensions = dimensions or settings.KNOWLEDGE_EMBEDDING_DIMENSIONS
        self.model_name = f"hashing-{self.dimensions}"

    def _embed(self, text):
        vector = [0.0] * self.dimensions
        tokens = [t.lower() for t in TOKEN_RE.findall(text)]
        features = tokens + [f"{a}_{b}" for a, b in zip(tokens, tokens[1:], strict=False)]
        for feature in features:
            digest = hashlib.blake2b(feature.encode(), digest_size=8).digest()
            bucket = int.from_bytes(digest[:4], "little") % self.dimensions
            sign = 1.0 if digest[4] & 1 else -1.0
            vector[bucket] += sign
        norm = math.sqrt(sum(v * v for v in vector)) or 1.0
        return [v / norm for v in vector]

    def embed_documents(self, texts):
        return [self._embed(t) for t in texts]

    def embed_query(self, text):
        return self._embed(text)


class VoyageEmbedder:
    URL = "https://api.voyageai.com/v1/embeddings"
    BATCH = 128

    def __init__(self):
        if not settings.VOYAGE_API_KEY:
            raise EmbeddingError("VOYAGE_API_KEY is not configured.")
        self.model_name = settings.VOYAGE_EMBEDDING_MODEL

    def _call(self, texts, input_type):
        try:
            response = requests.post(
                self.URL,
                headers={"Authorization": f"Bearer {settings.VOYAGE_API_KEY}"},
                json={"input": texts, "model": self.model_name, "input_type": input_type},
                timeout=60,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise EmbeddingError(f"Embedding request failed: {exc}") from exc
        data = sorted(response.json()["data"], key=lambda d: d["index"])
        return [d["embedding"] for d in data]

    def embed_documents(self, texts):
        vectors = []
        for i in range(0, len(texts), self.BATCH):
            vectors.extend(self._call(texts[i:i + self.BATCH], "document"))
        return vectors

    def embed_query(self, text):
        return self._call([text], "query")[0]


def get_embedder():
    provider = settings.KNOWLEDGE_EMBEDDING_PROVIDER
    if provider == "hashing":
        return HashingEmbedder()
    if provider == "voyage":
        return VoyageEmbedder()
    raise EmbeddingError(f"Unknown embedding provider {provider!r}.")
