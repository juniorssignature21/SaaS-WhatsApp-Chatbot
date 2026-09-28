"""Inbound webhook from the WhatsApp Business Platform.

One webhook URL serves every tenant: the tenant is resolved from the
``phone_number_id`` in the payload, never from anything the caller chooses.
The view only verifies, stores and enqueues; the AI runs in Celery.
"""

import hashlib
import hmac
import json
import logging
from datetime import datetime
from datetime import timezone as dt_timezone

from django.conf import settings
from django.db import transaction
from django.http import HttpResponse, HttpResponseForbidden, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from conversations.models import Message
from conversations.services import get_active_conversation, record_inbound
from customers.services import get_or_create_customer

from .models import WhatsAppAccount

logger = logging.getLogger(__name__)

# Ordering used so late/out-of-order status callbacks never move a message backwards.
STATUS_RANK = {
    Message.Status.PENDING: 0,
    Message.Status.SENT: 1,
    Message.Status.DELIVERED: 2,
    Message.Status.READ: 3,
}
STATUS_MAP = {
    "sent": Message.Status.SENT,
    "delivered": Message.Status.DELIVERED,
    "read": Message.Status.READ,
    "failed": Message.Status.FAILED,
}


def verify_signature(raw_body, signature_header):
    secret = settings.WHATSAPP_APP_SECRET
    if not secret or not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header.removeprefix("sha256="))


@csrf_exempt
@require_http_methods(["GET", "POST"])
def whatsapp_webhook(request):
    if request.method == "GET":
        return _verify_subscription(request)

    if not verify_signature(request.body, request.headers.get("X-Hub-Signature-256", "")):
        logger.warning("Rejected WhatsApp webhook with invalid signature")
        return HttpResponseForbidden("invalid signature")

    try:
        payload = json.loads(request.body)
    except ValueError:
        return JsonResponse({"error": "invalid json"}, status=400)

    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            if change.get("field") != "messages":
                continue
            try:
                handle_change(change.get("value", {}))
            except Exception:  # noqa: BLE001 - never make Meta retry the whole batch
                logger.exception("Failed to process WhatsApp webhook change")
    # Always 200 quickly; Meta retries non-2xx responses.
    return JsonResponse({"status": "ok"})


def _verify_subscription(request):
    mode = request.GET.get("hub.mode")
    token = request.GET.get("hub.verify_token", "")
    challenge = request.GET.get("hub.challenge", "")
    expected = settings.WHATSAPP_VERIFY_TOKEN
    if mode == "subscribe" and expected and hmac.compare_digest(token, expected):
        return HttpResponse(challenge, content_type="text/plain")
    return HttpResponseForbidden("verification failed")


def handle_change(value):
    phone_number_id = value.get("metadata", {}).get("phone_number_id")
    account = (
        WhatsAppAccount.objects.select_related("business")
        .filter(phone_number_id=phone_number_id, status=WhatsAppAccount.Status.ACTIVE)
        .first()
    )
    if account is None:
        logger.info("Webhook for unknown or disabled phone_number_id %s", phone_number_id)
        return
    if not account.business.is_active:
        logger.info("Webhook for suspended business %s", account.business_id)
        return

    WhatsAppAccount.objects.filter(pk=account.pk).update(last_webhook_at=timezone.now())

    names = {c.get("wa_id"): c.get("profile", {}).get("name", "") for c in value.get("contacts", [])}
    for raw in value.get("messages", []):
        handle_inbound_message(account, raw, names.get(raw.get("from"), ""))
    for status in value.get("statuses", []):
        handle_status(account, status)


def handle_inbound_message(account, raw, profile_name=""):
    from chatbot.tasks import process_incoming_message

    from .tasks import mark_whatsapp_message_read

    sender = raw.get("from")
    wamid = raw.get("id")
    if not sender or not wamid:
        return None

    message_type, content = extract_content(raw)
    sent_at = _parse_timestamp(raw.get("timestamp"))
    with transaction.atomic():
        customer = get_or_create_customer(account.business, sender, profile_name)
        conversation = get_active_conversation(account.business, customer, whatsapp_account=account)
        message, created = record_inbound(
            conversation, content, message_type=message_type, external_id=wamid,
            metadata={"raw_type": raw.get("type"), "context": raw.get("context")}, sent_at=sent_at,
        )
        if created:
            transaction.on_commit(lambda: mark_whatsapp_message_read.delay(message.id))
            transaction.on_commit(lambda: process_incoming_message.delay(message.id))
    return message


def handle_status(account, status):
    new_status = STATUS_MAP.get(status.get("status"))
    wamid = status.get("id")
    if not new_status or not wamid:
        return
    message = Message.objects.filter(business_id=account.business_id, external_id=wamid).first()
    if message is None:
        return
    if new_status == Message.Status.FAILED:
        errors = status.get("errors") or [{}]
        message.status = Message.Status.FAILED
        message.error = f"{errors[0].get('code', '')} {errors[0].get('title', '')}".strip()
        message.save(update_fields=["status", "error", "updated_at"])
    elif STATUS_RANK.get(new_status, 0) > STATUS_RANK.get(message.status, -1):
        message.status = new_status
        message.save(update_fields=["status", "updated_at"])


def extract_content(raw):
    """Return (message_type, text) for any inbound WhatsApp message type."""
    kind = raw.get("type", "unsupported")
    body = raw.get(kind, {}) if isinstance(raw.get(kind), dict) else {}
    if kind == "text":
        return Message.Type.TEXT, body.get("body", "")
    if kind == "interactive":
        reply = body.get("button_reply") or body.get("list_reply") or {}
        return Message.Type.INTERACTIVE, reply.get("title", "")
    if kind == "button":
        return Message.Type.BUTTON, body.get("text", "")
    if kind in {"image", "video", "document"}:
        caption = body.get("caption", "")
        label = f"[Customer sent a {kind}{': ' + body['filename'] if body.get('filename') else ''}]"
        return kind, f"{label} {caption}".strip()
    if kind in {"audio", "sticker"}:
        return kind, f"[Customer sent a {kind}]"
    if kind == "location":
        parts = [body.get("name"), body.get("address"), f"({body.get('latitude')}, {body.get('longitude')})"]
        return Message.Type.LOCATION, "[Customer shared a location] " + " ".join(p for p in parts if p)
    if kind == "contacts":
        return Message.Type.CONTACTS, "[Customer shared contact details]"
    if kind == "reaction":
        return Message.Type.REACTION, f"[Customer reacted {body.get('emoji', '')}]"
    return Message.Type.UNSUPPORTED, "[Customer sent an unsupported message type]"


def _parse_timestamp(value):
    try:
        return datetime.fromtimestamp(int(value), tz=dt_timezone.utc)
    except (TypeError, ValueError):
        return None
