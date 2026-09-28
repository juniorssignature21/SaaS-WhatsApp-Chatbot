"""LLM provider abstraction.

The orchestrator talks to ``LLMProvider``; each provider owns its wire format
for assistant turns and tool results, so the tool loop stays provider-agnostic.
"""

import logging
from dataclasses import dataclass, field

import anthropic
from django.conf import settings

logger = logging.getLogger(__name__)


class LLMError(Exception):
    """Raised for failures where the caller should send the fallback message."""

    def __init__(self, message, retryable=False):
        super().__init__(message)
        self.retryable = retryable


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict


@dataclass
class LLMResponse:
    text: str
    tool_calls: list
    stop_reason: str
    assistant_turn: dict  # message to append to `messages` before tool results
    usage: dict = field(default_factory=dict)
    refused: bool = False


class LLMProvider:
    def create(self, *, model, system, messages, tools, max_tokens, effort=""):
        raise NotImplementedError

    def tool_results_turn(self, results):
        """``results`` is a list of (ToolCall, ToolResult); returns a user message."""
        raise NotImplementedError


class AnthropicProvider(LLMProvider):
    # Models that accept server-side refusal fallbacks with the "default" routing mode.
    SERVER_FALLBACK_MODELS = {"claude-opus-5", "claude-fable-5-1"}
    FALLBACK_BETA = "server-side-fallback-2026-07-01"

    def __init__(self, client=None):
        self.client = client or anthropic.Anthropic(
            api_key=settings.ANTHROPIC_API_KEY or None,
            timeout=settings.CHATBOT_LLM_TIMEOUT,
            max_retries=2,
        )

    def create(self, *, model, system, messages, tools, max_tokens, effort=""):
        params = {
            "model": model,
            "max_tokens": max_tokens,
            # The system prompt is stable per business, so it caches across turns.
            "system": [{"type": "text", "text": system}],
            "messages": messages,
            "cache_control": {"type": "ephemeral"},
        }
        if tools:
            params["tools"] = [t.to_api() for t in tools]
        if effort:
            params["output_config"] = {"effort": effort}
        if not model.startswith("claude-haiku"):
            params["thinking"] = {"type": "adaptive"}

        try:
            if model in self.SERVER_FALLBACK_MODELS:
                response = self.client.beta.messages.create(
                    **params, betas=[self.FALLBACK_BETA], fallbacks="default"
                )
            else:
                response = self.client.messages.create(**params)
        except (anthropic.BadRequestError, anthropic.AuthenticationError,
                anthropic.PermissionDeniedError, anthropic.NotFoundError) as exc:
            raise LLMError(f"LLM request rejected: {exc.__class__.__name__}: {exc}") from exc
        except anthropic.RateLimitError as exc:
            raise LLMError("LLM rate limited", retryable=True) from exc
        except anthropic.APIStatusError as exc:
            raise LLMError(f"LLM API error {exc.status_code}", retryable=exc.status_code >= 500) from exc
        except anthropic.APIConnectionError as exc:
            raise LLMError("LLM connection error", retryable=True) from exc

        content = self._echoable_content(response.content)
        text = "".join(b.text for b in content if b.type == "text").strip()
        tool_calls = [ToolCall(b.id, b.name, b.input) for b in content if b.type == "tool_use"]
        usage = response.usage
        return LLMResponse(
            text=text,
            tool_calls=tool_calls,
            stop_reason=response.stop_reason,
            assistant_turn={"role": "assistant", "content": content},
            usage={
                "input_tokens": usage.input_tokens or 0,
                "output_tokens": usage.output_tokens or 0,
                "cache_read_tokens": getattr(usage, "cache_read_input_tokens", 0) or 0,
            },
            refused=response.stop_reason == "refusal",
        )

    @staticmethod
    def _echoable_content(content):
        """Drop pre-fallback model-internal blocks after a mid-output server fallback.

        Text before the last ``fallback`` marker is kept; thinking and tool_use
        blocks from the declined attempt must not be echoed or executed.
        """
        boundary = max((i for i, b in enumerate(content) if b.type == "fallback"), default=None)
        if boundary is None:
            return list(content)
        before = [b for b in content[:boundary] if b.type == "text"]
        return before + list(content[boundary + 1:])

    def tool_results_turn(self, results):
        return {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": call.id, "content": result.content,
                 **({"is_error": True} if result.is_error else {})}
                for call, result in results
            ],
        }


class EchoProvider(LLMProvider):
    """Offline provider for local development and tests: no network calls.

    Replies ``"Echo: <last customer message>"``; if the customer asks for a
    human and the handoff tool is available, it calls that tool first.
    """

    def create(self, *, model, system, messages, tools, max_tokens, effort=""):
        last = messages[-1]
        if isinstance(last["content"], list) and last["content"] and last["content"][0].get("type") == "tool_result":
            text = "Done: " + "; ".join(str(b["content"]) for b in last["content"])
            return self._text(text)
        user_text = _last_text(last)
        tool_names = {t.name for t in tools}
        if "handoff_to_human" in tool_names and "human" in user_text.lower():
            call = ToolCall("toolu_echo_1", "handoff_to_human", {"reason": "Customer asked for a human."})
            return LLMResponse(
                text="", tool_calls=[call], stop_reason="tool_use",
                assistant_turn={"role": "assistant", "content": [
                    {"type": "tool_use", "id": call.id, "name": call.name, "input": call.input}]},
            )
        return self._text(f"Echo: {user_text.split(chr(10))[-1]}")

    @staticmethod
    def _text(text):
        return LLMResponse(
            text=text, tool_calls=[], stop_reason="end_turn",
            assistant_turn={"role": "assistant", "content": [{"type": "text", "text": text}]},
            usage={"input_tokens": 0, "output_tokens": 0},
        )

    def tool_results_turn(self, results):
        return AnthropicProvider.tool_results_turn(self, results)


def _last_text(message):
    content = message["content"]
    if isinstance(content, str):
        return content
    return "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")


_PROVIDERS = {"anthropic": AnthropicProvider, "fake": EchoProvider, "echo": EchoProvider}


def get_provider():
    name = settings.CHATBOT_LLM_PROVIDER
    try:
        return _PROVIDERS[name]()
    except KeyError as exc:
        raise LLMError(f"Unknown LLM provider {name!r}") from exc
