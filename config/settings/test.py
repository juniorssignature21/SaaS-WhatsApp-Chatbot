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
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
PAYSTACK_SECRET_KEY = "sk_test_paystack"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

REST_FRAMEWORK = {
    **REST_FRAMEWORK,  # noqa: F405
    "DEFAULT_THROTTLE_CLASSES": [],
    "DEFAULT_THROTTLE_RATES": {"anon": None, "user": None, "auth": "10000/min", "playground": "10000/min"},
}

LOGGING["root"]["level"] = "ERROR"  # noqa: F405
