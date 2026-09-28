import time
from unittest import mock

from django.test import TestCase
from django.urls import reverse

from accounts import totp
from accounts.models import User
from common.testing import add_member, make_business, make_user, make_whatsapp_account
from conversations.models import Conversation, Message
from conversations.services import get_active_conversation, record_inbound
from customers.services import get_or_create_customer
from knowledge.models import KnowledgeDocument
from tenants.models import Role


class DashboardTestCase(TestCase):
    def setUp(self):
        self.business, self.owner = make_business("Mama Put")
        self.account = make_whatsapp_account(self.business)
        customer = get_or_create_customer(self.business, "2348066666666", "Chidi")
        self.conversation = get_active_conversation(self.business, customer, whatsapp_account=self.account)
        record_inbound(self.conversation, "Do you have jollof today?")
        self.client.force_login(self.owner)


class PageSmokeTests(DashboardTestCase):
    def test_every_page_renders_for_owner(self):
        names = ["overview", "inbox", "new_conversation", "customers", "whatsapp", "bot", "bot_playground",
                 "knowledge", "tools", "tool_new", "team", "billing", "settings", "account", "mfa_setup",
                 "audit", "notifications", "create_business"]
        for name in names:
            response = self.client.get(reverse(f"dashboard:{name}"))
            self.assertEqual(response.status_code, 200, name)
        for name, arg in [("conversation", self.conversation.id), ("customer", self.conversation.customer_id)]:
            self.assertEqual(self.client.get(reverse(f"dashboard:{name}", args=[arg])).status_code, 200, name)
        inbox = self.client.get(reverse("dashboard:inbox"))
        self.assertContains(inbox, "Chidi")

    def test_anonymous_is_redirected_to_login(self):
        self.client.logout()
        response = self.client.get(reverse("dashboard:inbox"))
        self.assertRedirects(response, f"{reverse('dashboard:login')}?next={reverse('dashboard:inbox')}")
        self.assertEqual(self.client.get("/").status_code, 302)


class PermissionTests(DashboardTestCase):
    def test_viewer_cannot_reach_admin_pages_or_act(self):
        self.client.force_login(add_member(self.business, Role.VIEWER))
        for name in ["whatsapp", "tools", "billing", "settings", "audit"]:
            self.assertEqual(self.client.get(reverse(f"dashboard:{name}")).status_code, 403, name)
        response = self.client.post(reverse("dashboard:conversation_action", args=[self.conversation.id, "reply"]),
                                    {"content": "hi"})
        self.assertEqual(response.status_code, 403)

    def test_other_tenants_objects_are_invisible(self):
        _, stranger = make_business("Rival")
        self.client.force_login(stranger)
        self.assertEqual(self.client.get(reverse("dashboard:conversation", args=[self.conversation.id])).status_code,
                         404)
        self.assertEqual(self.client.get(reverse("dashboard:conversation_poll",
                                                 args=[self.conversation.id])).status_code, 404)
        # Switching to a business you don't belong to is refused.
        response = self.client.post(reverse("dashboard:switch_business", args=[self.business.id]))
        self.assertEqual(response.status_code, 403)


class InboxActionTests(DashboardTestCase):
    def test_reply_takes_over_and_poll_returns_it(self):
        url = reverse("dashboard:conversation_action", args=[self.conversation.id, "reply"])
        with mock.patch("whatsapp.tasks.WhatsAppClient.send_text", return_value="wamid.d") as send:
            with self.captureOnCommitCallbacks(execute=True):
                self.client.post(url, {"content": "Yes, fresh jollof!"})
        send.assert_called_once_with("2348066666666", "Yes, fresh jollof!")
        self.conversation.refresh_from_db()
        self.assertEqual(self.conversation.status, Conversation.Status.HUMAN_HANDLING)
        poll = self.client.get(reverse("dashboard:conversation_poll", args=[self.conversation.id]), {"after": 0})
        self.assertIn("Yes, fresh jollof!", poll.json()["html"])

        self.client.post(reverse("dashboard:conversation_action", args=[self.conversation.id, "return"]))
        self.conversation.refresh_from_db()
        self.assertEqual(self.conversation.status, Conversation.Status.AI_HANDLING)

    def test_playground(self):
        response = self.client.post(reverse("dashboard:bot_playground"), {"message": "Hi there"}, follow=True)
        self.assertContains(response, "Echo: Hi there")
        self.assertFalse(Conversation.objects.filter(channel="SANDBOX").exclude(
            messages__role=Message.Role.ASSISTANT).exists())

    def test_add_faq_knowledge(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse("dashboard:knowledge"), {
                "source_type": "FAQ", "title": "FAQ",
                "faq_text": "Q: Do you deliver?\nA: Yes, within Lagos.\n\nQ: Opening hours?\nA: 9am-9pm."})
        document = KnowledgeDocument.objects.get(business=self.business)
        self.assertEqual(document.status, "READY")
        self.assertIn("Q: Opening hours?", document.raw_text)
        response = self.client.get(reverse("dashboard:knowledge"), {"q": "deliver"})
        self.assertContains(response, "within Lagos")

    def test_update_bot_settings(self):
        self.client.post(reverse("dashboard:bot"), {
            "name": "Mama Bot", "system_prompt": "Be warm.", "model": "claude-opus-5", "max_tokens": 2048,
            "effort": "low", "language": "auto", "welcome_message": "", "fallback_message": "Sorry!",
            "history_limit": 10, "enabled": "on", "rag_enabled": "on"})
        config = self.business.ai_config
        config.refresh_from_db()
        self.assertEqual((config.name, config.effort, config.human_handoff_enabled), ("Mama Bot", "low", False))


class AuthFlowTests(TestCase):
    def test_signup_then_login_with_mfa(self):
        response = self.client.post(reverse("dashboard:signup"), {
            "business_name": "Suya Spot", "full_name": "Musa", "email": "musa@example.com",
            "password": "S3cure-pass-123"})
        self.assertRedirects(response, reverse("dashboard:overview"))
        user = User.objects.get(email="musa@example.com")
        self.client.get(reverse("dashboard:mfa_setup"))
        user.refresh_from_db()
        self.client.post(reverse("dashboard:mfa_setup"), {"code": totp.current_code(user.mfa_secret)})
        user.refresh_from_db()
        self.assertTrue(user.mfa_enabled)
        self.client.post(reverse("dashboard:logout"))

        response = self.client.post(reverse("dashboard:login"), {"email": "musa@example.com",
                                                                 "password": "S3cure-pass-123"})
        self.assertRedirects(response, reverse("dashboard:login_mfa"))
        self.assertEqual(self.client.get(reverse("dashboard:overview")).status_code, 302)  # not signed in yet
        self.client.post(reverse("dashboard:login_mfa"), {"code": "000000"})
        self.assertEqual(self.client.get(reverse("dashboard:overview")).status_code, 302)
        user.refresh_from_db()
        # The setup code can't be replayed; use the next time step's code.
        code = totp.current_code(user.mfa_secret, now=time.time() + 30)
        response = self.client.post(reverse("dashboard:login_mfa"), {"code": code})
        self.assertRedirects(response, reverse("dashboard:overview"))

    def test_login_lockout(self):
        make_user(email="locked@example.com")
        for _ in range(10):
            self.client.post(reverse("dashboard:login"), {"email": "locked@example.com", "password": "wrong"})
        response = self.client.post(reverse("dashboard:login"), {"email": "locked@example.com",
                                                                 "password": "S3cure-pass-123"}, follow=True)
        self.assertContains(response, "Too many attempts")
