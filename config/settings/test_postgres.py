import dj_database_url

from .base import env
from .test import *  # noqa: F401,F403

DATABASES = {
    "default": dj_database_url.parse(env("DATABASE_URL", "postgres://postgres:postgres@localhost:5432/whatsapp_ai_saas"))
}
