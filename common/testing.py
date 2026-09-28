"""Helpers shared by the test suites."""

import hashlib
import hmac
import itertools
import json

from django.conf import settings
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from accounts.models import User
from tenants.models import Membership
from tenants.services import create_business
from whatsapp.models import WhatsAppAccount

_counter = itertools.count(1)


def make_user(email=None, password="S3cure-pass-123", verified=True):
    return User.objects.create_user(
        email=email or f"user{next(_counter)}@example.com", password=password, email_verified=verified
    )


def make_business(name="Acme", owner=None, plan="business"):
    from billing.models import Plan

    owner = owner or make_user()
    business = create_business(owner=owner, name=name)
    business.subscription.plan = Plan.objects.get(code=plan)
    business.subscription.save()
    return business, owner


def add_member(business, role, user=None):
    user = user or make_user()
    Membership.objects.create(user=user, business=business, role=role)
    return user


def api_client(user, business=None):
    client = APIClient()
    token, _ = Token.objects.get_or_create(user=user)
    client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
    if business is not None:
        client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}", HTTP_X_BUSINESS_ID=str(business.id))
    return client


def make_whatsapp_account(business, phone_number_id=None):
    n = next(_counter)
    return WhatsAppAccount.objects.create(
        business=business,
        phone_number=f"+23480000000{n:02d}",
        phone_number_id=phone_number_id or f"pnid-{n}",
        business_account_id=f"waba-{n}",
        access_token=f"secret-token-{n}",
    )


def text_message_payload(phone_number_id, sender, body, wamid=None, name="Ada"):
    return {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "waba",
            "changes": [{
                "field": "messages",
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {"display_phone_number": "2348000000000", "phone_number_id": phone_number_id},
                    "contacts": [{"profile": {"name": name}, "wa_id": sender}],
                    "messages": [{
                        "from": sender,
                        "id": wamid or f"wamid.in.{next(_counter)}",
                        "timestamp": "1760000000",
                        "type": "text",
                        "text": {"body": body},
                    }],
                },
            }],
        }],
    }


def status_payload(phone_number_id, wamid, status):
    return {
        "object": "whatsapp_business_account",
        "entry": [{"id": "waba", "changes": [{"field": "messages", "value": {
            "metadata": {"phone_number_id": phone_number_id},
            "statuses": [{"id": wamid, "status": status, "timestamp": "1760000001", "recipient_id": "234"}],
        }}]}],
    }


def post_webhook(client, payload, secret=None):
    body = json.dumps(payload).encode()
    signature = hmac.new((secret or settings.WHATSAPP_APP_SECRET).encode(), body, hashlib.sha256).hexdigest()
    return client.post(
        "/webhooks/whatsapp/", data=body, content_type="application/json",
        HTTP_X_HUB_SIGNATURE_256=f"sha256={signature}",
    )
