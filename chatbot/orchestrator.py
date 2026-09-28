"""AI orchestration: turn an inbound customer message into a reply.

    load config -> guard checks -> history -> knowledge (RAG) -> tools
      -> LLM <-> tool loop -> response guard -> save + send -> usage
"""

import logging
from dataclasses import dataclass, field

from django.conf import settings
from django.db import transaction

from billing.services import ai_quota_available, has_feature, record_usage
from conversations.models import Conversation, Message
from conversations.services import handoff_to_human, send_outbound
from knowledge import retrieval
from tools.base import ToolContext
from tools.registry import describe_args, get_tools, run_tool

from .llm import LLMError, get_provider
from .memory import build_history
from .prompts import build_system_prompt, format_knowledge

logger = logging.getLogger(__name__)

HANDOFF_ACK = "Thanks for your patience. A member of our team will reply to you here shortly."


@dataclass
class Outcome:
    action: str  # "replied", "skipped", "handoff", "fallback"
    reason: str = ""
    reply: Message | None = None
    usage: dict = field(default_factory=dict)


def handle_incoming_message(message_id, provider=None):
    message = (
        Message.objects.select_related("conversation__customer", "conversation__business__ai_config")
        .filter(pk=message_id, role=Message.Role.USER)
        .first()
    )
    if message is None:
        return Outcome("skipped", "message not found")
    conversation = message.conversation
    business = conversation.business

    skip = _skip_reason(message, conversation, business)
    if skip:
        return Outcome("skipped", skip)

    config = business.ai_config
    if not ai_quota_available(business):
        with transaction.atomic():
            handoff_to_human(conversation, reason="Monthly AI response limit reached.")
        return Outcome("handoff", "quota exhausted")

    return _generate_reply(message, conversation, business, config, provider or get_provider())


def _skip_reason(message, conversation, business):
    if not business.is_active:
        return "business suspended"
    config = getattr(business, "ai_config", None)
    if config is None or not config.enabled:
        return "AI disabled"
    conversation.refresh_from_db(fields=["status"])
    if not conversation.ai_enabled:
        return f"conversation is {conversation.status}"
    later = conversation.messages.filter(id__gt=message.id)
    # Debounce bursts: only the newest customer message gets a reply (with full context).
    if later.filter(role=Message.Role.USER).exists():
        return "newer customer message pending"
    if later.filter(role__in=[Message.Role.ASSISTANT, Message.Role.AGENT]).exists():
        return "already answered"
    return ""


def _generate_reply(message, conversation, business, config, provider):
    history = build_history(
        conversation, config.history_limit, up_to_message=message, memory_enabled=config.memory_enabled
    )
    if not history:
        return Outcome("skipped", "no customer text to answer")

    knowledge = []
    if config.rag_enabled and has_feature(business, "rag") and message.content.strip():
        knowledge = retrieval.search(business, message.content)
        if knowledge:
            history[-1] = {
                "role": "user",
                "content": [
                    {"type": "text", "text": format_knowledge(knowledge)},
                    {"type": "text", "text": history[-1]["content"]},
                ],
            }

    system = build_system_prompt(config, business)
    tools = get_tools(business, config)
    ctx = ToolContext(business=business, conversation=conversation, customer=conversation.customer)
    usage = {"input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0}
    tools_used = []
    messages = list(history)
    text = None

    for _ in range(settings.CHATBOT_MAX_TOOL_ITERATIONS):
        response = provider.create(
            model=config.model, system=system, messages=messages, tools=tools,
            max_tokens=config.max_tokens, effort=config.effort,
        )
        for key in usage:
            usage[key] += response.usage.get(key, 0)

        if response.refused:
            logger.info("LLM refused a reply in conversation %s", conversation.id)
            text = config.fallback_message
            break
        # Never execute tool calls from a truncated response.
        if not response.tool_calls or response.stop_reason == "max_tokens":
            text = response.text
            break

        messages.append(response.assistant_turn)
        results = []
        for call in response.tool_calls:
            result = run_tool(tools, call.name, call.input, ctx)
            results.append((call, result))
            tools_used.append(call.name)
            Message.objects.create(
                business=business, conversation=conversation, role=Message.Role.TOOL,
                direction=Message.Direction.INTERNAL, status=Message.Status.SENT,
                content=f"{call.name}({describe_args(call.input)}) -> {result.content[:1000]}",
                metadata={"tool": call.name, "is_error": result.is_error},
            )
        messages.append(provider.tool_results_turn(results))

    handed_off = bool(ctx.effects.get("handoff"))
    text = _guard(text, config, handed_off)
    record_usage(business, tool_calls=len(tools_used), **usage)

    with transaction.atomic():
        current = Conversation.objects.select_for_update().get(pk=conversation.pk)
        if current.status == Conversation.Status.HUMAN_HANDLING and not handed_off:
            # A human took over while we were thinking; stay quiet.
            return Outcome("skipped", "human took over during generation", usage=usage)
        reply = send_outbound(
            current, text, Message.Role.ASSISTANT,
            metadata={
                "model": config.model,
                "usage": usage,
                "tools": tools_used,
                "knowledge_chunks": [k.chunk_id for k in knowledge],
                "in_reply_to": message.id,
            },
        )
    return Outcome("handoff" if handed_off else "replied", reply=reply, usage=usage)


def _guard(text, config, handed_off):
    """Final checks before anything is sent to a customer."""
    text = (text or "").strip()
    if not text:
        return HANDOFF_ACK if handed_off else config.fallback_message
    limit = settings.WHATSAPP_MAX_TEXT_LENGTH
    if len(text) > limit:
        text = text[: limit - 1].rsplit(" ", 1)[0] + "…"
    return text


def send_fallback(message_id, error=""):
    """Used when the LLM is unavailable after retries: apologise and escalate."""
    message = Message.objects.select_related("conversation__business__ai_config").filter(pk=message_id).first()
    if message is None:
        return None
    conversation = message.conversation
    config = conversation.business.ai_config
    with transaction.atomic():
        current = Conversation.objects.select_for_update().get(pk=conversation.pk)
        if not current.ai_enabled:
            return None
        reply = send_outbound(current, config.fallback_message, Message.Role.ASSISTANT,
                              metadata={"fallback": True, "error": error[:500]})
        if config.human_handoff_enabled:
            handoff_to_human(current, reason="The AI assistant was unavailable.")
    return reply


__all__ = ["handle_incoming_message", "send_fallback", "LLMError", "Outcome"]
