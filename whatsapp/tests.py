from unittest import mock

from django.db import connection
from django.test import Client, TestCase

from common.testing import (
    make_business,
    make_whatsapp_account,
    post_webhook,
    status_payload,
    text_message_payload,
)
from conversations.models import Conversation, Message
from customers.models import Customer

from .client import WhatsAppAPIError
from .models import WhatsAppAccount


def fake_send():
    counter = iter(range(1, 10_000))
    return mock.patch(
        "whatsapp.tasks.WhatsAppClient.send_text", side_effect=lambda *a, **k: f"wamid.out.{next(counter)}"
    )


@mock.patch("whatsapp.tasks.WhatsAppClient.mark_as_read")
class WebhookTests(TestCase):
    def setUp(self):
        self.business, self.owner = make_business("Foodies")
        self.account = make_whatsapp_account(self.business, "pnid-foodies")
        self.client = Client()

    def deliver(self, payload, **kwargs):
        with self.captureOnCommitCallbacks(execute=True):
            return post_webhook(self.client, payload, **kwargs)

    def test_subscription_verification(self, _read):
        ok = self.client.get("/webhooks/whatsapp/", {
            "hub.mode": "subscribe", "hub.verify_token": "test-verify-token", "hub.challenge": "42"})
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(ok.content, b"42")
        bad = self.client.get("/webhooks/whatsapp/", {
            "hub.mode": "subscribe", "hub.verify_token": "wrong", "hub.challenge": "42"})
        self.assertEqual(bad.status_code, 403)

    def test_rejects_bad_signature(self, _read):
        payload = text_message_payload("pnid-foodies", "2348011111111", "hi")
        response = post_webhook(self.client, payload, secret="not-the-secret")
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Message.objects.exists())

    def test_inbound_message_gets_ai_reply(self, _read):
        with fake_send() as send:
            response = self.deliver(text_message_payload("pnid-foodies", "2348011111111", "What time do you open?"))
        self.assertEqual(response.status_code, 200)

        customer = Customer.objects.get(business=self.business, phone_number="2348011111111")
        self.assertEqual(customer.name, "Ada")
        conversation = Conversation.objects.get(customer=customer)
        self.assertEqual(conversation.whatsapp_account, self.account)
        roles = list(conversation.messages.values_list("role", "status"))
        self.assertEqual(roles, [("USER", "RECEIVED"), ("ASSISTANT", "SENT")])
        send.assert_called_once_with("2348011111111", "Echo: What time do you open?")
        reply = conversation.messages.get(role="ASSISTANT")
        self.assertTrue(reply.external_id.startswith("wamid.out."))

    def test_duplicate_webhook_is_idempotent(self, _read):
        payload = text_message_payload("pnid-foodies", "2348011111111", "hello", wamid="wamid.dup")
        with fake_send() as send:
            self.deliver(payload)
            self.deliver(payload)
        self.assertEqual(Message.objects.filter(role="USER").count(), 1)
        self.assertEqual(send.call_count, 1)

    def test_status_updates_never_go_backwards(self, _read):
        with fake_send():
            self.deliver(text_message_payload("pnid-foodies", "2348011111111", "hello"))
        reply = Message.objects.get(role="ASSISTANT")
        self.deliver(status_payload("pnid-foodies", reply.external_id, "read"))
        self.deliver(status_payload("pnid-foodies", reply.external_id, "delivered"))
        reply.refresh_from_db()
        self.assertEqual(reply.status, "READ")

    def test_unknown_number_is_ignored(self, _read):
        response = self.deliver(text_message_payload("pnid-unknown", "2348011111111", "hello"))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Message.objects.exists())

    def test_same_phone_is_a_different_customer_per_business(self, _read):
        other, _ = make_business("Hotel")
        make_whatsapp_account(other, "pnid-hotel")
        with fake_send():
            self.deliver(text_message_payload("pnid-foodies", "2348011111111", "menu?"))
            self.deliver(text_message_payload("pnid-hotel", "2348011111111", "rooms?"))
        self.assertEqual(Customer.objects.filter(phone_number="2348011111111").count(), 2)
        hotel_conv = Conversation.objects.get(business=other)
        self.assertEqual(list(hotel_conv.messages.values_list("content", flat=True)), ["rooms?", "Echo: rooms?"])

    def test_failed_delivery_is_recorded(self, _read):
        error = WhatsAppAPIError("Re-engagement message", status_code=400, code=131047)
        with mock.patch("whatsapp.tasks.WhatsAppClient.send_text", side_effect=error):
            self.deliver(text_message_payload("pnid-foodies", "2348011111111", "hello"))
        reply = Message.objects.get(role="ASSISTANT")
        self.assertEqual(reply.status, "FAILED")
        self.assertIn("131047", reply.error)


class EncryptionTests(TestCase):
    def test_access_token_is_encrypted_at_rest(self):
        business, _ = make_business()
        account = make_whatsapp_account(business)
        with connection.cursor() as cursor:
            cursor.execute("SELECT access_token FROM whatsapp_whatsappaccount WHERE id = %s", [account.id])
            stored = cursor.fetchone()[0]
        self.assertTrue(stored.startswith("enc::"))
        self.assertNotIn("secret-token", stored)
        self.assertTrue(WhatsAppAccount.objects.get(pk=account.pk).access_token.startswith("secret-token-"))
