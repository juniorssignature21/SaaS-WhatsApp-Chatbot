"""Turn stored conversation messages into LLM chat history."""

from conversations.models import Message

ROLE_MAP = {
    Message.Role.USER: "user",
    Message.Role.ASSISTANT: "assistant",
    Message.Role.AGENT: "assistant",
}


def build_history(conversation, limit, up_to_message=None, memory_enabled=True):
    """Return alternating user/assistant messages ending with a user turn.

    Human-agent replies are presented as assistant turns (prefixed so the model
    knows a colleague said it). Consecutive same-role messages are merged.
    """
    qs = conversation.messages.filter(role__in=ROLE_MAP.keys()).exclude(status=Message.Status.FAILED)
    if up_to_message is not None:
        qs = qs.filter(id__lte=up_to_message.id)
    if not memory_enabled:
        limit = 1
    rows = list(qs.order_by("-created_at", "-id")[:limit])[::-1]

    turns = []
    for message in rows:
        role = ROLE_MAP[message.role]
        text = message.content.strip() or f"[{message.message_type} message]"
        if message.role == Message.Role.AGENT:
            text = f"[Human team member]: {text}"
        if turns and turns[-1]["role"] == role:
            turns[-1]["content"] += "\n" + text
        else:
            turns.append({"role": role, "content": text})

    # The API expects the conversation to start with a user turn.
    while turns and turns[0]["role"] != "user":
        turns.pop(0)
    if not turns or turns[-1]["role"] != "user":
        return []
    return turns
