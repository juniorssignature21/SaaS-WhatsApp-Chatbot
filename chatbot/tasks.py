import logging

from celery import shared_task
from django.core.cache import cache

from conversations.models import Message

from .llm import LLMError
from .orchestrator import handle_incoming_message, send_fallback

logger = logging.getLogger(__name__)

LOCK_TIMEOUT = 300


@shared_task(bind=True, max_retries=3)
def process_incoming_message(self, message_id):
    conversation_id = Message.objects.filter(pk=message_id).values_list("conversation_id", flat=True).first()
    if conversation_id is None:
        return "skipped: message not found"

    # One AI turn at a time per conversation, without holding a DB transaction
    # open for the duration of the LLM call.
    lock_key = f"chatbot:conversation-lock:{conversation_id}"
    if not cache.add(lock_key, self.request.id or "eager", LOCK_TIMEOUT):
        raise self.retry(countdown=3, max_retries=20)
    try:
        outcome = handle_incoming_message(message_id)
    except LLMError as exc:
        if exc.retryable and self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=5 * 2 ** self.request.retries) from exc
        logger.error("AI reply failed for message %s: %s", message_id, exc)
        send_fallback(message_id, error=str(exc))
        return "fallback"
    finally:
        cache.delete(lock_key)
    return f"{outcome.action}: {outcome.reason}".rstrip(": ")
