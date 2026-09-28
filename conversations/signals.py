from django.dispatch import Signal

# Sent with conversation=..., reason=... when a conversation needs a human.
# Hook notifications (email, push, dashboard websocket) onto this.
handoff_requested = Signal()
