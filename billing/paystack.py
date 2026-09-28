"""Minimal Paystack API client (https://paystack.com/docs/api/)."""

import hashlib
import hmac
from decimal import Decimal

import requests
from django.conf import settings


class PaystackError(Exception):
    pass


def _request(method, path, **kwargs):
    if not settings.PAYSTACK_SECRET_KEY:
        raise PaystackError("Payments are not configured (PAYSTACK_SECRET_KEY).")
    try:
        response = requests.request(
            method, f"{settings.PAYSTACK_BASE_URL}{path}",
            headers={"Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}"}, timeout=20, **kwargs,
        )
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise PaystackError(f"Payment provider unavailable: {exc.__class__.__name__}") from exc
    if response.status_code >= 400 or not payload.get("status"):
        raise PaystackError(payload.get("message") or f"HTTP {response.status_code}")
    return payload.get("data", {})


def to_subunit(amount):
    """Naira -> kobo (Paystack amounts are in the currency's smallest unit)."""
    return int((Decimal(amount) * 100).quantize(Decimal("1")))


def initialize_transaction(email, amount, reference, callback_url, plan_code="", metadata=None):
    data = {
        "email": email, "amount": to_subunit(amount), "reference": reference,
        "callback_url": callback_url, "metadata": metadata or {},
    }
    if plan_code:
        data["plan"] = plan_code  # creates a recurring Paystack subscription
    return _request("POST", "/transaction/initialize", json=data)


def verify_transaction(reference):
    return _request("GET", f"/transaction/verify/{reference}")


def disable_subscription(code, email_token):
    return _request("POST", "/subscription/disable", json={"code": code, "token": email_token})


def valid_signature(raw_body, signature):
    if not settings.PAYSTACK_SECRET_KEY or not signature:
        return False
    expected = hmac.new(settings.PAYSTACK_SECRET_KEY.encode(), raw_body, hashlib.sha512).hexdigest()
    return hmac.compare_digest(expected, signature)
