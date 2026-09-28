from celery import shared_task
from django.conf import settings

from .services import auto_resolve_idle


@shared_task
def auto_resolve_idle_conversations():
    return auto_resolve_idle(settings.CONVERSATION_AUTO_RESOLVE_HOURS)
