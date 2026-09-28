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
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
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
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
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
MEDIA_URL = "media/"
MEDIA_ROOT = Path(env("MEDIA_ROOT", str(BASE_DIR / "media")))

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------------------------------------------------------------------
# REST framework
# ---------------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.TokenAuthentication",
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

# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------
TOOLS_HTTP_TIMEOUT = float(env("TOOLS_HTTP_TIMEOUT", "10"))
# Outbound HTTP tools may never reach private/internal addresses unless this
# is explicitly enabled (SSRF protection).
TOOLS_ALLOW_PRIVATE_NETWORKS = env_bool("TOOLS_ALLOW_PRIVATE_NETWORKS", False)

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
