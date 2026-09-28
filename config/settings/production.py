from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F401,F403
from .base import FIELD_ENCRYPTION_KEYS, SECRET_KEY, WHATSAPP_APP_SECRET, env_bool

DEBUG = False

if SECRET_KEY.startswith("insecure-"):
    raise ImproperlyConfigured("DJANGO_SECRET_KEY must be set in production.")
if not FIELD_ENCRYPTION_KEYS:
    raise ImproperlyConfigured("FIELD_ENCRYPTION_KEYS must be set in production.")
if not WHATSAPP_APP_SECRET:
    raise ImproperlyConfigured("WHATSAPP_APP_SECRET must be set in production.")

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", True)
SECURE_HSTS_SECONDS = 60 * 60 * 24 * 30
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
