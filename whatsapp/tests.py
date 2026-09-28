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


TEMPLATE_API_DATA = [
    {"id": "1", "name": "order_update", "language": "en", "status": "APPROVED", "category": "UTILITY",
     "components": [{"type": "BODY", "text": "Hi {{1}}, your order {{2}} has shipped."}]},
    {"id": "2", "name": "promo", "language": "en", "status": "APPROVED", "category": "MARKETING",
     "components": [{"type": "HEADER", "format": "IMAGE"}, {"type": "BODY", "text": "Sale!"}]},
    {"id": "3", "name": "pending_one", "language": "en", "status": "PENDING", "components": []},
]


class TemplateTests(TestCase):
    def setUp(self):
        from common.testing import api_client

        self.business, self.owner = make_business("Shop")
        self.account = make_whatsapp_account(self.business, "pnid-shop")
        self.api = api_client(self.owner)
        with mock.patch("whatsapp.services.WhatsAppClient.list_templates", return_value=TEMPLATE_API_DATA):
            response = self.api.post(f"/api/v1/whatsapp/accounts/{self.account.id}/sync-templates/")
        self.assertEqual(response.data["synced"], 3)

    def test_sync_and_sendability(self):
        from .models import MessageTemplate

        order = MessageTemplate.objects.get(name="order_update")
        self.assertEqual(order.parameter_count, 2)
        self.assertTrue(order.is_sendable)
        self.assertFalse(MessageTemplate.objects.get(name="promo").is_sendable)
        self.assertFalse(MessageTemplate.objects.get(name="pending_one").is_sendable)
        # Re-sync removes templates deleted in WhatsApp Manager.
        from .services import sync_templates

        with mock.patch("whatsapp.services.WhatsAppClient.list_templates", return_value=TEMPLATE_API_DATA[:1]):
            sync_templates(self.account)
        self.assertEqual(MessageTemplate.objects.count(), 1)

    def test_start_conversation_with_template(self):
        from .models import MessageTemplate

        template = MessageTemplate.objects.get(name="order_update")
        with mock.patch("whatsapp.tasks.WhatsAppClient.send_template", return_value="wamid.tpl") as send:
            with self.captureOnCommitCallbacks(execute=True):
                response = self.api.post("/api/v1/conversations/start/", {
                    "whatsapp_account_id": self.account.id, "phone_number": "+2348033333333",
                    "template_id": template.id, "params": ["Ada", "1045"], "name": "Ada"}, format="json")
        self.assertEqual(response.status_code, 201, response.content)
        send.assert_called_once_with("2348033333333", "order_update", "en", ["Ada", "1045"])
        message = Message.objects.get(message_type="template")
        self.assertEqual(message.content, "Hi Ada, your order 1045 has shipped.")
        self.assertEqual(message.status, "SENT")
        conversation = message.conversation
        self.assertEqual(conversation.status, Conversation.Status.HUMAN_HANDLING)
        self.assertEqual(conversation.assigned_agent, self.owner)

        # No inbound yet -> free-form replies are blocked (24h rule).
        blocked = self.api.post(f"/api/v1/conversations/{conversation.id}/reply/", {"content": "hi"}, format="json")
        self.assertEqual(blocked.status_code, 409)
        self.assertEqual(blocked.data["code"], "service_window_closed")

    def test_wrong_param_count_and_unapproved(self):
        from .models import MessageTemplate

        for name, params in [("order_update", ["only one"]), ("promo", []), ("pending_one", [])]:
            template = MessageTemplate.objects.get(name=name)
            response = self.api.post("/api/v1/conversations/start/", {
                "whatsapp_account_id": self.account.id, "phone_number": "2348033333333",
                "template_id": template.id, "params": params}, format="json")
            self.assertEqual(response.status_code, 400, name)


@mock.patch("whatsapp.tasks.WhatsAppClient.mark_as_read")
class MediaTests(TestCase):
    def setUp(self):
        self.business, _ = make_business("Photos")
        make_whatsapp_account(self.business, "pnid-photos")

    def image_payload(self, kind="image", mime="image/png", caption="Is this in stock?"):
        payload = text_message_payload("pnid-photos", "2348044444444", "")
        raw = payload["entry"][0]["changes"][0]["value"]["messages"][0]
        raw.pop("text")
        raw["type"] = kind
        raw[kind] = {"id": "media-123", "mime_type": mime, "caption": caption}
        return payload

    def test_image_is_downloaded_and_sent_to_the_model(self, _read):
        from chatbot.llm import EchoProvider

        seen = {}

        class Capture(EchoProvider):
            def create(self, **kwargs):
                seen["content"] = kwargs["messages"][-1]["content"]
                return super().create(**kwargs)

        png = b"\x89PNG\r\n\x1a\nfake"
        with mock.patch("whatsapp.media.WhatsAppClient.get_media",
                        return_value={"url": "https://lookaside.fbsbx.com/x", "mime_type": "image/png"}), \
             mock.patch("whatsapp.media.WhatsAppClient.download", return_value=png), \
             mock.patch("chatbot.orchestrator.get_provider", return_value=Capture()), \
             fake_send():
            with self.captureOnCommitCallbacks(execute=True):
                post_webhook(Client(), self.image_payload())

        inbound = Message.objects.get(role="USER")
        self.assertEqual(inbound.media_mime_type, "image/png")
        self.assertTrue(inbound.media.name.startswith(f"messages/{self.business.id}/"))
        image_block = next(b for b in seen["content"] if b["type"] == "image")
        self.assertEqual(image_block["source"]["media_type"], "image/png")
        self.assertIn("Is this in stock?", seen["content"][-1]["text"])

    @mock.patch("chatbot.transcription.requests.post")
    def test_voice_note_is_transcribed(self, post, _read):
        post.return_value = mock.Mock(status_code=200, json=lambda: {"text": "Do you open on Sunday?"},
                                      raise_for_status=lambda: None)
        with self.settings(TRANSCRIPTION_PROVIDER="whisper_http", TRANSCRIPTION_API_URL="https://stt.example/v1"), \
             mock.patch("whatsapp.media.WhatsAppClient.get_media",
                        return_value={"url": "https://lookaside.fbsbx.com/a", "mime_type": "audio/ogg"}), \
             mock.patch("whatsapp.media.WhatsAppClient.download", return_value=b"OggS..."), \
             fake_send() as send:
            with self.captureOnCommitCallbacks(execute=True):
                post_webhook(Client(), self.image_payload(kind="audio", mime="audio/ogg; codecs=opus", caption=""))
        inbound = Message.objects.get(role="USER")
        self.assertEqual(inbound.content, "[Voice note] Do you open on Sunday?")
        send.assert_called_once()
        self.assertIn("Do you open on Sunday?", send.call_args.args[1])

    def test_media_endpoint_is_tenant_scoped(self, _read):
        from django.core.files.base import ContentFile

        from common.testing import api_client

        conversation = Conversation.objects.create(
            business=self.business, customer=Customer.objects.create(business=self.business, phone_number="1"))
        message = Message.objects.create(business=self.business, conversation=conversation, role="USER",
                                         direction="INBOUND", media_mime_type="image/png")
        message.media.save("x.png", ContentFile(b"img"))
        owner = self.business.memberships.get().user
        self.assertEqual(api_client(owner).get(f"/api/v1/message-media/{message.id}/").status_code, 200)
        other, other_owner = make_business("Other")
        self.assertEqual(api_client(other_owner).get(f"/api/v1/message-media/{message.id}/").status_code, 404)
