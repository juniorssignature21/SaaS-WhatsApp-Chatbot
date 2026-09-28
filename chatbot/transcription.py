"""Voice-note transcription.

``whisper_http`` works with any OpenAI-compatible ``/audio/transcriptions``
endpoint (hosted Whisper APIs or a self-hosted faster-whisper server).
"""

import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


class TranscriptionError(Exception):
    pass


class WhisperHTTPTranscriber:
    def transcribe(self, data, mime_type, filename="audio.ogg"):
        if not settings.TRANSCRIPTION_API_URL:
            raise TranscriptionError("TRANSCRIPTION_API_URL is not configured.")
        headers = {}
        if settings.TRANSCRIPTION_API_KEY:
            headers["Authorization"] = f"Bearer {settings.TRANSCRIPTION_API_KEY}"
        try:
            response = requests.post(
                settings.TRANSCRIPTION_API_URL,
                headers=headers,
                data={"model": settings.TRANSCRIPTION_MODEL},
                files={"file": (filename, data, mime_type)},
                timeout=60,
            )
            response.raise_for_status()
            return response.json().get("text", "").strip()
        except (requests.RequestException, ValueError) as exc:
            raise TranscriptionError(f"Transcription failed: {exc.__class__.__name__}") from exc


def get_transcriber():
    if settings.TRANSCRIPTION_PROVIDER == "whisper_http":
        return WhisperHTTPTranscriber()
    return None


def transcribe_message(message):
    """Replace a voice note's placeholder text with its transcript. Returns True on success."""
    transcriber = get_transcriber()
    if transcriber is None or not message.media or message.metadata.get("transcribed"):
        return False
    try:
        with message.media.open("rb") as fh:
            text = transcriber.transcribe(fh.read(), message.media_mime_type or "audio/ogg")
    except TranscriptionError as exc:
        logger.info("Could not transcribe message %s: %s", message.pk, exc)
        return False
    if not text:
        return False
    message.content = f"[Voice note] {text}"
    message.metadata = {**message.metadata, "transcribed": True}
    message.save(update_fields=["content", "metadata", "updated_at"])
    return True
