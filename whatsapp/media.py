"""Download media customers send (images, voice notes, documents)."""

import logging
import mimetypes

from django.conf import settings
from django.core.files.base import ContentFile

from .client import WhatsAppAPIError, WhatsAppClient

logger = logging.getLogger(__name__)


def download_message_media(message):
    account = message.conversation.whatsapp_account
    media_id = message.metadata.get("media_id")
    if account is None or not media_id or account.business_id != message.business_id:
        return None
    client = WhatsAppClient(account)
    try:
        info = client.get_media(media_id)
        data = client.download(info["url"], settings.MEDIA_MAX_DOWNLOAD_BYTES)
    except (WhatsAppAPIError, KeyError) as exc:
        logger.info("Could not download media for message %s: %s", message.pk, exc)
        message.metadata = {**message.metadata, "media_error": str(exc)[:300]}
        message.save(update_fields=["metadata", "updated_at"])
        return None
    mime = (info.get("mime_type") or message.metadata.get("mime_type") or "application/octet-stream")
    mime = mime.split(";")[0].strip()
    extension = mimetypes.guess_extension(mime) or ".bin"
    message.media_mime_type = mime
    message.media.save(f"{message.pk}{extension}", ContentFile(data), save=False)
    message.save(update_fields=["media", "media_mime_type", "updated_at"])
    return message
