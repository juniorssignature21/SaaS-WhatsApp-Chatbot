"""Thin client for the WhatsApp Business Cloud API (Graph API)."""

import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


class WhatsAppAPIError(Exception):
    def __init__(self, message, status_code=None, code=None, retryable=False):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.retryable = retryable


class WhatsAppClient:
    def __init__(self, account):
        self.account = account
        self.base_url = f"{settings.WHATSAPP_GRAPH_API_URL}/{settings.WHATSAPP_GRAPH_API_VERSION}"

    def _request(self, method, path, **kwargs):
        headers = {"Authorization": f"Bearer {self.account.access_token}"}
        try:
            response = requests.request(
                method, f"{self.base_url}/{path}", headers=headers,
                timeout=settings.WHATSAPP_REQUEST_TIMEOUT, **kwargs,
            )
        except requests.RequestException as exc:
            raise WhatsAppAPIError(f"Network error: {exc.__class__.__name__}", retryable=True) from exc

        try:
            payload = response.json()
        except ValueError:
            payload = {}
        if response.status_code >= 400:
            error = payload.get("error", {}) if isinstance(payload, dict) else {}
            # Never log the token; the error body from Meta does not contain it.
            raise WhatsAppAPIError(
                error.get("message") or f"HTTP {response.status_code}",
                status_code=response.status_code,
                code=error.get("code"),
                retryable=response.status_code == 429 or response.status_code >= 500,
            )
        return payload

    def send_text(self, to, body, reply_to=None):
        """Send a text message; returns the WhatsApp message id (wamid)."""
        data = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "text",
            "text": {"preview_url": False, "body": body},
        }
        if reply_to:
            data["context"] = {"message_id": reply_to}
        payload = self._request("POST", f"{self.account.phone_number_id}/messages", json=data)
        return payload["messages"][0]["id"]

    def mark_as_read(self, message_id):
        self._request(
            "POST", f"{self.account.phone_number_id}/messages",
            json={"messaging_product": "whatsapp", "status": "read", "message_id": message_id},
        )

    def get_phone_number_info(self):
        return self._request(
            "GET", self.account.phone_number_id,
            params={"fields": "display_phone_number,verified_name,quality_rating"},
        )
