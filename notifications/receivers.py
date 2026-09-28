from django.dispatch import receiver

from conversations.signals import handoff_requested

from .services import notify_handoff


@receiver(handoff_requested)
def on_handoff(sender, conversation, reason="", actor=None, **kwargs):
    # A person taking over deliberately doesn't need an alert; the bot or customer asking does.
    if conversation.channel == "SANDBOX" or actor is not None:
        return
    notify_handoff(conversation, reason)
