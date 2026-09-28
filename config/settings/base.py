"""Base settings shared by every environment.

All secrets and environment-specific values come from environment variables.
"""

import os
from pathlib import Path

import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent.parent


def env(name, default=None):
    return os.environ.get(name, default)


def env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_list(name, default=""):
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


SECRET_KEY = env("DJANGO_SECRET_KEY", "insecure-dev-key-change-me")
DEBUG = env_bool("DJANGO_DEBUG", False)
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "rest_framework.authtoken",
    # Local apps
    "accounts",
    "tenants",
    "customers",
    "conversations",
    "whatsapp",
    "chatbot",
    "knowledge",
    "tools",
    "billing",
    "analytics",
    "notifications",
    "dashboard",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "dashboard.context_processors.dashboard",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DATABASES = {
    "default": dj_database_url.parse(
        env("DATABASE_URL", "postgres://postgres:postgres@localhost:5432/whatsapp_ai_saas"),
        conn_max_age=int(env("DATABASE_CONN_MAX_AGE", "60")),
    )
}

AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
MEDIA_URL = "media/"
MEDIA_ROOT = Path(env("MEDIA_ROOT", str(BASE_DIR / "media")))

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------------------------------------------------------------------
# REST framework
# ---------------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.TokenAuthentication",
        "tenants.authentication.APIKeyAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 50,
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": env("THROTTLE_ANON", "30/min"),
        "user": env("THROTTLE_USER", "600/min"),
        "auth": env("THROTTLE_AUTH", "10/min"),
        "playground": env("THROTTLE_PLAYGROUND", "20/min"),
    },
}

# ---------------------------------------------------------------------------
# Celery / Redis
# ---------------------------------------------------------------------------
REDIS_URL = env("REDIS_URL", "redis://localhost:6379/0")
CELERY_BROKER_URL = env("CELERY_BROKER_URL", REDIS_URL)
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", REDIS_URL)
CELERY_TASK_ACKS_LATE = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_TASK_ALWAYS_EAGER = env_bool("CELERY_TASK_ALWAYS_EAGER", False)
CELERY_TASK_ROUTES = {
    "chatbot.tasks.*": {"queue": "ai"},
    "whatsapp.tasks.*": {"queue": "whatsapp"},
    "knowledge.tasks.*": {"queue": "knowledge"},
}

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,
    }
}

# ---------------------------------------------------------------------------
# Security: encryption of credentials at rest
# ---------------------------------------------------------------------------
# Comma-separated Fernet keys. The first key encrypts; all keys decrypt
# (supports key rotation). Generate with:
#   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
FIELD_ENCRYPTION_KEYS = env_list("FIELD_ENCRYPTION_KEYS")

# ---------------------------------------------------------------------------
# WhatsApp Business Platform (Cloud API)
# ---------------------------------------------------------------------------
WHATSAPP_GRAPH_API_URL = env("WHATSAPP_GRAPH_API_URL", "https://graph.facebook.com")
WHATSAPP_GRAPH_API_VERSION = env("WHATSAPP_GRAPH_API_VERSION", "v21.0")
# Token you configure in the Meta app dashboard for webhook verification.
WHATSAPP_VERIFY_TOKEN = env("WHATSAPP_VERIFY_TOKEN", "")
# Meta app secret used to verify the X-Hub-Signature-256 header.
WHATSAPP_APP_SECRET = env("WHATSAPP_APP_SECRET", "")
WHATSAPP_REQUEST_TIMEOUT = float(env("WHATSAPP_REQUEST_TIMEOUT", "15"))
# WhatsApp's hard limit for a text message body.
WHATSAPP_MAX_TEXT_LENGTH = 4096

# ---------------------------------------------------------------------------
# Chatbot / LLM
# ---------------------------------------------------------------------------
# "anthropic" in production; "fake" gives deterministic replies for tests/dev.
CHATBOT_LLM_PROVIDER = env("CHATBOT_LLM_PROVIDER", "anthropic")
CHATBOT_DEFAULT_MODEL = env("CHATBOT_DEFAULT_MODEL", "claude-opus-5")
CHATBOT_MAX_TOOL_ITERATIONS = int(env("CHATBOT_MAX_TOOL_ITERATIONS", "5"))
CHATBOT_LLM_TIMEOUT = float(env("CHATBOT_LLM_TIMEOUT", "120"))
ANTHROPIC_API_KEY = env("ANTHROPIC_API_KEY")

# ---------------------------------------------------------------------------
# Knowledge base / RAG
# ---------------------------------------------------------------------------
# "hashing" is a dependency-free local embedding (good for dev/tests);
# "voyage" calls the Voyage AI embeddings API.
KNOWLEDGE_EMBEDDING_PROVIDER = env("KNOWLEDGE_EMBEDDING_PROVIDER", "hashing")
KNOWLEDGE_EMBEDDING_DIMENSIONS = int(env("KNOWLEDGE_EMBEDDING_DIMENSIONS", "512"))
VOYAGE_API_KEY = env("VOYAGE_API_KEY")
VOYAGE_EMBEDDING_MODEL = env("VOYAGE_EMBEDDING_MODEL", "voyage-3.5")
KNOWLEDGE_CHUNK_SIZE = int(env("KNOWLEDGE_CHUNK_SIZE", "1200"))
KNOWLEDGE_CHUNK_OVERLAP = int(env("KNOWLEDGE_CHUNK_OVERLAP", "200"))
KNOWLEDGE_TOP_K = int(env("KNOWLEDGE_TOP_K", "5"))
KNOWLEDGE_MAX_UPLOAD_BYTES = int(env("KNOWLEDGE_MAX_UPLOAD_BYTES", str(20 * 1024 * 1024)))
KNOWLEDGE_MAX_CRAWL_PAGES = int(env("KNOWLEDGE_MAX_CRAWL_PAGES", "50"))

# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------
TOOLS_HTTP_TIMEOUT = float(env("TOOLS_HTTP_TIMEOUT", "10"))
# Outbound HTTP tools may never reach private/internal addresses unless this
# is explicitly enabled (SSRF protection).
TOOLS_ALLOW_PRIVATE_NETWORKS = env_bool("TOOLS_ALLOW_PRIVATE_NETWORKS", False)

# ---------------------------------------------------------------------------
# Site, email and accounts
# ---------------------------------------------------------------------------
PLATFORM_NAME = env("PLATFORM_NAME", "WhatsApp AI")
# Public base URL used in emails and payment callbacks.
SITE_URL = env("SITE_URL", "http://localhost:8000").rstrip("/")
LOGIN_URL = "dashboard:login"
LOGIN_REDIRECT_URL = "dashboard:overview"
EMAIL_BACKEND = env("EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")
EMAIL_HOST = env("EMAIL_HOST", "localhost")
EMAIL_PORT = int(env("EMAIL_PORT", "587"))
EMAIL_HOST_USER = env("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", "no-reply@localhost")
# Owners must verify their email before connecting a WhatsApp number.
REQUIRE_EMAIL_VERIFICATION = env_bool("REQUIRE_EMAIL_VERIFICATION", True)
EMAIL_VERIFICATION_MAX_AGE = 60 * 60 * 24 * 3
MFA_CHALLENGE_MAX_AGE = 60 * 5
SESSION_COOKIE_AGE = 60 * 60 * 24 * 7
SESSION_COOKIE_HTTPONLY = True

# ---------------------------------------------------------------------------
# Conversations and media
# ---------------------------------------------------------------------------
# WhatsApp only allows free-form messages within 24h of the customer's last message.
WHATSAPP_SERVICE_WINDOW_HOURS = 24
# AI conversations idle for this long are resolved automatically (0 disables).
CONVERSATION_AUTO_RESOLVE_HOURS = int(env("CONVERSATION_AUTO_RESOLVE_HOURS", "24"))
MEDIA_MAX_DOWNLOAD_BYTES = int(env("MEDIA_MAX_DOWNLOAD_BYTES", str(20 * 1024 * 1024)))
# Voice-note transcription: "none", or "whisper_http" for any OpenAI-compatible
# /audio/transcriptions endpoint (hosted or self-hosted Whisper).
TRANSCRIPTION_PROVIDER = env("TRANSCRIPTION_PROVIDER", "none")
TRANSCRIPTION_API_URL = env("TRANSCRIPTION_API_URL", "")
TRANSCRIPTION_API_KEY = env("TRANSCRIPTION_API_KEY", "")
TRANSCRIPTION_MODEL = env("TRANSCRIPTION_MODEL", "whisper-1")

# ---------------------------------------------------------------------------
# Billing (Paystack)
# ---------------------------------------------------------------------------
PAYSTACK_SECRET_KEY = env("PAYSTACK_SECRET_KEY", "")
PAYSTACK_BASE_URL = env("PAYSTACK_BASE_URL", "https://api.paystack.co")
TRIAL_DAYS = int(env("TRIAL_DAYS", "14"))
BILLING_GRACE_DAYS = int(env("BILLING_GRACE_DAYS", "3"))

# ---------------------------------------------------------------------------
# Scheduled jobs (celery beat)
# ---------------------------------------------------------------------------
CELERY_BEAT_SCHEDULE = {
    "auto-resolve-idle-conversations": {
        "task": "conversations.tasks.auto_resolve_idle_conversations",
        "schedule": 60 * 15,
    },
    "expire-subscriptions": {"task": "billing.tasks.expire_subscriptions", "schedule": 60 * 60},
    "sync-whatsapp-templates": {"task": "whatsapp.tasks.sync_all_templates", "schedule": 60 * 60 * 6},
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "standard"},
    },
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", "INFO")},
}
