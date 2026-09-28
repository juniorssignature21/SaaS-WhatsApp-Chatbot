import logging

from celery import shared_task
from django.db import transaction

from conversations.models import Message

from .client import WhatsAppAPIError, WhatsAppClient
from .models import WhatsAppAccount
from .services import sync_templates

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=5)
def send_whatsapp_message(self, message_id):
    with transaction.atomic():
        message = (
            Message.objects.select_for_update(of=("self",))
            .select_related("conversation__customer", "conversation__whatsapp_account")
            .filter(pk=message_id)
            .first()
        )
        if message is None or message.status != Message.Status.PENDING:
            return  # already sent (task redelivery) or deleted
        conversation = message.conversation
        account = conversation.whatsapp_account
        if account is None or account.business_id != message.business_id:
            _fail(message, "No WhatsApp number connected for this conversation.")
            return

        try:
            client = WhatsAppClient(account)
            to = conversation.customer.phone_number
            if message.message_type == Message.Type.TEMPLATE:
                template = message.metadata["template"]
                wamid = client.send_template(to, template["name"], template["language"], template["params"])
            else:
                wamid = client.send_text(to, message.content)
        except WhatsAppAPIError as exc:
            if exc.retryable and self.request.retries < self.max_retries:
                raise self.retry(exc=exc, countdown=2 ** (self.request.retries + 1)) from exc
            # e.g. code 131047: outside the 24h customer-service window (needs a template).
            _fail(message, f"{exc.code or exc.status_code}: {exc}")
            return

        message.external_id = wamid
        message.status = Message.Status.SENT
        message.error = ""
        message.save(update_fields=["external_id", "status", "error", "updated_at"])


@shared_task
def mark_whatsapp_message_read(message_id):
    message = Message.objects.select_related("conversation__whatsapp_account").filter(pk=message_id).first()
    if not message or not message.external_id or not message.conversation.whatsapp_account:
        return
    try:
        WhatsAppClient(message.conversation.whatsapp_account).mark_as_read(message.external_id)
    except WhatsAppAPIError as exc:
        logger.info("Could not mark message %s read: %s", message_id, exc)


def _fail(message, error):
    logger.warning("WhatsApp delivery failed for message %s: %s", message.pk, error)
    message.status = Message.Status.FAILED
    message.error = error[:2000]
    message.save(update_fields=["status", "error", "updated_at"])


@shared_task
def sync_account_templates(account_id):
    account = WhatsAppAccount.objects.filter(pk=account_id, status=WhatsAppAccount.Status.ACTIVE).first()
    if account is None:
        return 0
    try:
        return sync_templates(account)
    except WhatsAppAPIError as exc:
        logger.info("Template sync failed for account %s: %s", account_id, exc)
        return 0


@shared_task
def sync_all_templates():
    for account_id in WhatsAppAccount.objects.filter(status=WhatsAppAccount.Status.ACTIVE).values_list("id", flat=True):
        sync_account_templates.delay(account_id)
