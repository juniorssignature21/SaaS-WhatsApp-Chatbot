"""Turn customer attachments into Claude content blocks (vision and PDF input)."""

import base64

from conversations.models import Message
from conversations.services import ensure_media

from .transcription import transcribe_message

IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_PDF_BYTES = 20 * 1024 * 1024


def pending_customer_messages(conversation, up_to_message):
    """Customer messages in the turn being answered (since the last reply)."""
    last_reply = (
        conversation.messages.filter(
            role__in=[Message.Role.ASSISTANT, Message.Role.AGENT], id__lt=up_to_message.id
        ).order_by("-id").values_list("id", flat=True).first()
    )
    qs = conversation.messages.filter(role=Message.Role.USER, id__lte=up_to_message.id)
    if last_reply:
        qs = qs.filter(id__gt=last_reply)
    return list(qs.order_by("id"))


def prepare(messages):
    """Download media and transcribe voice notes for the pending messages."""
    for message in messages:
        if message.metadata.get("media_id") and not message.media:
            ensure_media(message)
        if message.message_type == Message.Type.AUDIO:
            transcribe_message(message)


def content_blocks(messages):
    blocks = []
    for message in messages:
        if not message.media:
            continue
        mime = message.media_mime_type
        if mime in IMAGE_TYPES and message.media.size <= MAX_IMAGE_BYTES:
            source_type = "image"
        elif mime == "application/pdf" and message.media.size <= MAX_PDF_BYTES:
            source_type = "document"
        else:
            continue
        with message.media.open("rb") as fh:
            data = base64.standard_b64encode(fh.read()).decode()
        blocks.append({"type": source_type, "source": {"type": "base64", "media_type": mime, "data": data}})
    return blocks
