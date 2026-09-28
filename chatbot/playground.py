"""Try the bot from the dashboard without WhatsApp (sandbox channel)."""

from conversations.models import Channel, Conversation
from conversations.services import get_active_conversation, record_inbound, resolve
from customers.models import Customer

from .orchestrator import handle_incoming_message


def _sandbox_customer(business, user_key):
    customer, _ = Customer.objects.get_or_create(
        business=business, phone_number=f"sandbox-{user_key}"[:32],
        defaults={"name": "Playground", "metadata": {"sandbox": True}},
    )
    return customer


def playground_conversation(business, user_key):
    customer = _sandbox_customer(business, user_key)
    return get_active_conversation(business, customer, channel=Channel.SANDBOX)


def reset(business, user_key):
    customer = _sandbox_customer(business, user_key)
    for conversation in Conversation.objects.filter(
        business=business, customer=customer, status__in=Conversation.ACTIVE_STATUSES
    ):
        resolve(conversation)


def chat(business, user_key, text, provider=None):
    """Send ``text`` as the sandbox customer and run the assistant synchronously."""
    conversation = playground_conversation(business, user_key)
    if not conversation.ai_enabled:
        # e.g. the bot handed off during testing: start fresh.
        reset(business, user_key)
        conversation = playground_conversation(business, user_key)
    message, _ = record_inbound(conversation, text)
    outcome = handle_incoming_message(message.id, provider=provider, playground=True)
    return conversation, outcome
