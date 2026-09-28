"""Custom model fields shared across apps."""

import json

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import models


def _fernet():
    keys = settings.FIELD_ENCRYPTION_KEYS
    if not keys:
        raise ImproperlyConfigured(
            "FIELD_ENCRYPTION_KEYS is empty; cannot encrypt credentials at rest."
        )
    return MultiFernet([Fernet(key.encode() if isinstance(key, str) else key) for key in keys])


class EncryptedTextField(models.TextField):
    """Text field that is transparently encrypted at rest with Fernet.

    The first key in FIELD_ENCRYPTION_KEYS encrypts; every key can decrypt, so
    keys can be rotated by prepending a new key.
    Encrypted values cannot be filtered on.
    """

    PREFIX = "enc::"

    def from_db_value(self, value, expression, connection):
        if value is None or value == "":
            return value
        if not value.startswith(self.PREFIX):
            # Legacy plaintext value; returned as-is and encrypted on next save.
            return value
        try:
            return _fernet().decrypt(value[len(self.PREFIX):].encode()).decode()
        except InvalidToken as exc:
            raise ImproperlyConfigured(
                "Could not decrypt a stored credential; check FIELD_ENCRYPTION_KEYS."
            ) from exc

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        if value is None or value == "" or value.startswith(self.PREFIX):
            return value
        return self.PREFIX + _fernet().encrypt(value.encode()).decode()


class EmbeddingField(models.Field):
    """Stores an embedding vector.

    On PostgreSQL the column is a pgvector ``vector`` so similarity search runs
    in the database. Elsewhere (e.g. SQLite in tests) it is stored as JSON text
    and similarity is computed in Python.
    """

    description = "Embedding vector"

    def db_type(self, connection):
        if connection.vendor == "postgresql":
            return "vector"
        return "text"

    def from_db_value(self, value, expression, connection):
        return self.to_python(value)

    def to_python(self, value):
        if value is None or isinstance(value, list):
            return value
        if hasattr(value, "tolist"):
            return [float(v) for v in value.tolist()]
        # Both pgvector's text form "[1,2,3]" and our JSON form parse as JSON.
        return [float(v) for v in json.loads(value)]

    def get_prep_value(self, value):
        if value is None:
            return None
        return json.dumps([float(v) for v in value], separators=(",", ":"))
