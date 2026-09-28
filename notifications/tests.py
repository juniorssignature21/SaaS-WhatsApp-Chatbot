from django.core import mail
from django.test import TestCase

from common.testing import add_member, api_client, make_business
from conversations.services import get_active_conversation, handoff_to_human, record_inbound
from customers.services import get_or_create_customer
from tenants.models import Role

from .models import Notification


class HandoffNotificationTests(TestCase):
    def setUp(self):
        self.business, self.owner = make_business("Help")
        self.agent = add_member(self.business, Role.AGENT)
        self.viewer = add_member(self.business, Role.VIEWER)
        customer = get_or_create_customer(self.business, "2348055555555", "Bola")
        self.conversation = get_active_conversation(self.business, customer)
        record_inbound(self.conversation, "I need a person")

    def test_ai_handoff_notifies_agents_by_app_and_email(self):
        with self.captureOnCommitCallbacks(execute=True):
            handoff_to_human(self.conversation, reason="Customer asked for a person.")
        recipients = set(Notification.objects.values_list("user__email", flat=True))
        self.assertEqual(recipients, {self.owner.email, self.agent.email})
        self.assertEqual(sorted(m.to[0] for m in mail.outbox), sorted(recipients))
        self.assertIn("Bola needs a human", mail.outbox[0].subject)

        unread = api_client(self.agent).get("/api/v1/notifications/?unread=true").data["results"]
        self.assertEqual(len(unread), 1)
        api_client(self.agent).post("/api/v1/notifications/read-all/")
        self.assertEqual(api_client(self.agent).get("/api/v1/notifications/?unread=true").data["results"], [])

    def test_manual_takeover_does_not_notify(self):
        with self.captureOnCommitCallbacks(execute=True):
            handoff_to_human(self.conversation, reason="Taken over", actor=self.agent)
        self.assertFalse(Notification.objects.exists())
        self.assertEqual(len(mail.outbox), 0)

    def test_email_opt_out(self):
        membership = self.agent.memberships.get()
        membership.notify_by_email = False
        membership.save()
        with self.captureOnCommitCallbacks(execute=True):
            handoff_to_human(self.conversation, reason="x")
        self.assertEqual([m.to[0] for m in mail.outbox], [self.owner.email])
