"""Conversation lifecycle: inbound/outbound messages, handoff, resolution.

Channel-agnostic: channel adapters (whatsapp, ...) call into these functions
and are called back through ``deliver`` to send outbound messages.
"""

import logging
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from billing.services import record_usage

from .models import Channel, Conversation, Message
from .signals import handoff_requested

logger = logging.getLogger(__name__)


class ServiceWindowClosed(Exception):
    """Free-form messages are not allowed; a pre-approved template is required."""


def get_active_conversation(business, customer, channel=Channel.WHATSAPP, whatsapp_account=None):
    """Return the customer's active conversation, starting a new one if needed."""
    conversation = (
        Conversation.objects.filter(
            business=business, customer=customer, channel=channel,
            status__in=Conversation.ACTIVE_STATUSES,
        )
        .order_by("-last_message_at")
        .first()
    )
    if conversation is None:
        conversation = Conversation.objects.create(
            business=business, customer=customer, channel=channel, whatsapp_account=whatsapp_account,
        )
        record_usage(business, conversations=1)
    elif whatsapp_account is not None and conversation.whatsapp_account_id != whatsapp_account.id:
        conversation.whatsapp_account = whatsapp_account
        conversation.save(update_fields=["whatsapp_account", "updated_at"])
    return conversation


def record_inbound(conversation, content, message_type=Message.Type.TEXT, external_id="", metadata=None,
                   sent_at=None):
    """Store a customer message. Idempotent on ``external_id``.

    Returns ``(message, created)``; ``created`` is False for a webhook retry.
    """
    if external_id:
        existing = Message.objects.filter(business_id=conversation.business_id, external_id=external_id).first()
        if existing:
            return existing, False
    try:
        with transaction.atomic():
            message = Message.objects.create(
                business_id=conversation.business_id,
                conversation=conversation,
                role=Message.Role.USER,
                direction=Message.Direction.INBOUND,
                message_type=message_type,
                content=content,
                external_id=external_id,
                status=Message.Status.RECEIVED,
                metadata=metadata or {},
            )
    except IntegrityError:
        # Concurrent delivery of the same webhook.
        return Message.objects.get(business_id=conversation.business_id, external_id=external_id), False

    now = sent_at or timezone.now()
    updates = {"last_message_at": now, "updated_at": timezone.now()}
    if conversation.status == Conversation.Status.WAITING_FOR_CUSTOMER:
        updates["status"] = Conversation.Status.AI_HANDLING
    Conversation.objects.filter(pk=conversation.pk).update(**updates)
    for key, value in updates.items():
        setattr(conversation, key, value)
    record_usage(conversation.business, messages_in=1)
    return message, True


def send_outbound(conversation, content, role, sender=None, metadata=None, message_type=Message.Type.TEXT):
    """Store an outbound message and queue its delivery once the transaction commits."""
    message = Message.objects.create(
        business_id=conversation.business_id,
        conversation=conversation,
        role=role,
        direction=Message.Direction.OUTBOUND,
        message_type=message_type,
        content=content,
        status=Message.Status.PENDING,
        sender=sender,
        metadata=metadata or {},
    )
    now = timezone.now()
    Conversation.objects.filter(pk=conversation.pk).update(last_message_at=now, updated_at=now)
    conversation.last_message_at = now
    counter = "ai_responses" if role == Message.Role.ASSISTANT else "human_responses"
    record_usage(conversation.business, messages_out=1, **{counter: 1})
    transaction.on_commit(lambda: deliver(message.id, conversation.channel))
    return message


def deliver(message_id, channel):
    """Dispatch an outbound message to its channel adapter."""
    if channel == Channel.WHATSAPP:
        from whatsapp.tasks import send_whatsapp_message

        send_whatsapp_message.delay(message_id)
    elif channel == Channel.SANDBOX:
        Message.objects.filter(pk=message_id, status=Message.Status.PENDING).update(status=Message.Status.SENT)
    else:  # pragma: no cover - future channels
        logger.error("No channel adapter for %s", channel)


def add_system_note(conversation, content, sender=None):
    return Message.objects.create(
        business_id=conversation.business_id,
        conversation=conversation,
        role=Message.Role.SYSTEM,
        direction=Message.Direction.INTERNAL,
        content=content,
        status=Message.Status.SENT,
        sender=sender,
    )


def handoff_to_human(conversation, reason="", actor=None):
    """Stop the AI and route the conversation to the human team."""
    if conversation.status == Conversation.Status.HUMAN_HANDLING:
        return conversation
    conversation.status = Conversation.Status.HUMAN_HANDLING
    conversation.handoff_reason = reason[:500]
    fields = ["status", "handoff_reason", "updated_at"]
    if actor is not None:
        conversation.assigned_agent = actor
        fields.append("assigned_agent")
    conversation.save(update_fields=fields)
    add_system_note(conversation, f"Handed off to a human agent. {reason}".strip(), sender=actor)
    record_usage(conversation.business, escalations=1)
    handoff_requested.send(sender=Conversation, conversation=conversation, reason=reason, actor=actor)
    return conversation


def return_to_ai(conversation, actor=None):
    conversation.status = Conversation.Status.AI_HANDLING
    conversation.assigned_agent = None
    conversation.handoff_reason = ""
    conversation.save(update_fields=["status", "assigned_agent", "handoff_reason", "updated_at"])
    add_system_note(conversation, "Returned to the AI assistant.", sender=actor)
    return conversation


def resolve(conversation, actor=None):
    conversation.status = Conversation.Status.RESOLVED
    conversation.resolved_at = timezone.now()
    conversation.save(update_fields=["status", "resolved_at", "updated_at"])
    add_system_note(conversation, "Conversation resolved.", sender=actor)
    record_usage(conversation.business, resolved_conversations=1)
    return conversation


def agent_reply(conversation, content, agent):
    """A human agent replies; this implicitly takes the conversation over from the AI."""
    if not conversation.service_window_open:
        raise ServiceWindowClosed(
            "More than 24 hours have passed since the customer's last message. Send an approved template instead."
        )
    if agent is None:
        # API-key automation: reply as the team without assigning anyone.
        if conversation.status != Conversation.Status.HUMAN_HANDLING:
            handoff_to_human(conversation, reason="Replied through the API.")
        return send_outbound(conversation, content, Message.Role.AGENT)
    if conversation.status != Conversation.Status.HUMAN_HANDLING:
        handoff_to_human(conversation, reason="Agent replied manually.", actor=agent)
    elif conversation.assigned_agent_id is None:
        conversation.assigned_agent = agent
        conversation.save(update_fields=["assigned_agent", "updated_at"])
    return send_outbound(conversation, content, Message.Role.AGENT, sender=agent)


def send_template_message(conversation, template, params, sender=None):
    """Send a pre-approved WhatsApp template (works outside the 24h window)."""
    if conversation.channel != Channel.WHATSAPP:
        raise ValueError("Templates are only available on WhatsApp.")
    if template.business_id != conversation.business_id or not template.is_sendable:
        raise ValueError("This template is not approved for this business.")
    if conversation.whatsapp_account_id and template.whatsapp_account_id != conversation.whatsapp_account_id:
        raise ValueError("This template belongs to a different WhatsApp number.")
    params = [str(p) for p in params]
    if len(params) != template.parameter_count:
        raise ValueError(f"This template needs {template.parameter_count} value(s).")
    if sender is not None:
        # The agent who reaches out owns the follow-up.
        if conversation.status != Conversation.Status.HUMAN_HANDLING:
            handoff_to_human(conversation, reason="Agent sent a template message.", actor=sender)
        elif conversation.assigned_agent_id is None:
            conversation.assigned_agent = sender
            conversation.save(update_fields=["assigned_agent", "updated_at"])
    return send_outbound(
        conversation, template.render(params), Message.Role.AGENT, sender=sender,
        message_type=Message.Type.TEMPLATE,
        metadata={"template": {"name": template.name, "language": template.language, "params": params}},
    )


@transaction.atomic
def start_conversation(business, whatsapp_account, phone_number, template, params, sender=None, name=""):
    """Proactively message a customer (who may never have written) with a template."""
    from customers.services import get_or_create_customer

    if whatsapp_account.business_id != business.id:
        raise ValueError("Unknown WhatsApp number.")
    customer = get_or_create_customer(business, phone_number, name)
    conversation = get_active_conversation(business, customer, whatsapp_account=whatsapp_account)
    return send_template_message(conversation, template, params, sender=sender)


def ensure_media(message):
    """Download an inbound attachment through its channel adapter (idempotent)."""
    if message.media or not message.metadata.get("media_id"):
        return message
    if message.conversation.channel == Channel.WHATSAPP:
        from whatsapp.media import download_message_media

        download_message_media(message)
    return message


def auto_resolve_idle(hours, now=None):
    """Resolve AI-handled conversations with no activity for ``hours``. Returns the count."""
    if not hours:
        return 0
    cutoff = (now or timezone.now()) - timedelta(hours=hours)
    idle = Conversation.objects.filter(
        status__in=[Conversation.Status.OPEN, Conversation.Status.AI_HANDLING,
                    Conversation.Status.WAITING_FOR_CUSTOMER],
        last_message_at__lt=cutoff,
    )
    count = 0
    for conversation in idle.iterator():
        resolve(conversation)
        count += 1
    return count
