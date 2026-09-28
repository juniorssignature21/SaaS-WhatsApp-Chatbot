from .base import *  # noqa: F401,F403

DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

FIELD_ENCRYPTION_KEYS = ["yb_i0ZGb06oLsnvFL5cUvJrzqX6eq9tNCU_v8iVgUWA="]
WHATSAPP_VERIFY_TOKEN = "test-verify-token"
WHATSAPP_APP_SECRET = "test-app-secret"
CHATBOT_LLM_PROVIDER = "fake"
KNOWLEDGE_EMBEDDING_PROVIDER = "hashing"

REST_FRAMEWORK = {**REST_FRAMEWORK, "DEFAULT_THROTTLE_CLASSES": []}  # noqa: F405

LOGGING["root"]["level"] = "ERROR"  # noqa: F405
