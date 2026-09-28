from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from common.testing import make_business
from customers.services import get_or_create_customer

from .models import Conversation
from .services import auto_resolve_idle, get_active_conversation, handoff_to_human, record_inbound


class AutoResolveTests(TestCase):
    def test_resolves_only_idle_ai_conversations(self):
        business, _ = make_business()
        idle = get_active_conversation(business, get_or_create_customer(business, "1"))
        human = get_active_conversation(business, get_or_create_customer(business, "2"))
        fresh = get_active_conversation(business, get_or_create_customer(business, "3"))
        handoff_to_human(human, reason="x")
        old = timezone.now() - timedelta(hours=30)
        Conversation.objects.filter(pk__in=[idle.pk, human.pk]).update(last_message_at=old)

        self.assertEqual(auto_resolve_idle(24), 1)
        statuses = dict(Conversation.objects.values_list("pk", "status"))
        self.assertEqual(statuses[idle.pk], "RESOLVED")
        self.assertEqual(statuses[human.pk], "HUMAN_HANDLING")
        self.assertEqual(statuses[fresh.pk], "AI_HANDLING")

        # The next customer message starts a new conversation.
        new = get_active_conversation(business, idle.customer)
        record_inbound(new, "back again")
        self.assertNotEqual(new.pk, idle.pk)
