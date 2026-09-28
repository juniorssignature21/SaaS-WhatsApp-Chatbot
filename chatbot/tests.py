import json
from types import SimpleNamespace
from unittest import mock

from django.test import TestCase, override_settings

from billing.models import Plan
from common.testing import make_business, make_whatsapp_account
from conversations.models import Conversation, Message
from conversations.services import get_active_conversation, record_inbound, return_to_ai
from customers.services import get_or_create_customer
from knowledge.models import KnowledgeDocument
from knowledge.services import process_document
from tools.executors import sign
from tools.models import Tool

from .llm import AnthropicProvider, EchoProvider, LLMError, LLMResponse, ToolCall
from .memory import build_history
from .orchestrator import handle_incoming_message
from .tasks import process_incoming_message


class ScriptedProvider(EchoProvider):
    """Returns queued responses and records every request."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(json.loads(json.dumps(kwargs, default=lambda o: getattr(o, "name", str(o)))))
        return self.responses.pop(0)


def text_response(text, stop_reason="end_turn"):
    return LLMResponse(text=text, tool_calls=[], stop_reason=stop_reason,
                       assistant_turn={"role": "assistant", "content": [{"type": "text", "text": text}]},
                       usage={"input_tokens": 100, "output_tokens": 20, "cache_read_tokens": 80})


def tool_response(name, args, call_id="toolu_1"):
    call = ToolCall(call_id, name, args)
    return LLMResponse(text="", tool_calls=[call], stop_reason="tool_use",
                       assistant_turn={"role": "assistant", "content": [
                           {"type": "tool_use", "id": call_id, "name": name, "input": args}]},
                       usage={"input_tokens": 50, "output_tokens": 10})


def _unique_wamids():
    counter = iter(range(1, 10_000))
    return lambda *a, **k: f"wamid.out.{next(counter)}"


@mock.patch("whatsapp.tasks.WhatsAppClient.send_text", side_effect=_unique_wamids())
class OrchestratorTests(TestCase):
    def setUp(self):
        self.business, self.owner = make_business("Shop")
        self.account = make_whatsapp_account(self.business)
        self.customer = get_or_create_customer(self.business, "2348022222222", "Tolu")
        self.conversation = get_active_conversation(self.business, self.customer, whatsapp_account=self.account)

    def inbound(self, text):
        message, _ = record_inbound(self.conversation, text)
        return message

    def run_turn(self, text, provider):
        message = self.inbound(text)
        with self.captureOnCommitCallbacks(execute=True):
            return handle_incoming_message(message.id, provider=provider)

    def test_plain_reply_records_usage(self, send):
        provider = ScriptedProvider(text_response("We open at 9am."))
        outcome = self.run_turn("When do you open?", provider)
        self.assertEqual(outcome.action, "replied")
        send.assert_called_once_with("2348022222222", "We open at 9am.")
        request = provider.calls[0]
        self.assertEqual(request["model"], "claude-opus-5")
        self.assertIn("Shop", request["system"])
        self.assertEqual(request["messages"], [{"role": "user", "content": "When do you open?"}])
        usage = self.business.usage_records.get()
        self.assertEqual((usage.ai_responses, usage.input_tokens, usage.cache_read_tokens), (1, 100, 80))

    def test_history_includes_previous_turns_and_agent_messages(self, send):
        self.run_turn("Hi", ScriptedProvider(text_response("Hello!")))
        Message.objects.create(business=self.business, conversation=self.conversation, role="AGENT",
                               direction="OUTBOUND", content="I'm Sam from the team.", status="SENT")
        provider = ScriptedProvider(text_response("Sure."))
        self.run_turn("Thanks", provider)
        self.assertEqual(provider.calls[0]["messages"], [
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Hello!\n[Human team member]: I'm Sam from the team."},
            {"role": "user", "content": "Thanks"},
        ])

    def test_handoff_tool_stops_ai(self, send):
        provider = ScriptedProvider(
            tool_response("handoff_to_human", {"reason": "wants a person"}),
            text_response("Connecting you to a colleague now."),
        )
        outcome = self.run_turn("I want to talk to a human", provider)
        self.assertEqual(outcome.action, "handoff")
        self.conversation.refresh_from_db()
        self.assertEqual(self.conversation.status, Conversation.Status.HUMAN_HANDLING)
        # The tool result was fed back to the model.
        tool_turn = provider.calls[1]["messages"][-1]
        self.assertEqual(tool_turn["content"][0]["type"], "tool_result")
        self.assertTrue(Message.objects.filter(role="TOOL", content__startswith="handoff_to_human").exists())

        # While a human handles it, the AI stays silent.
        silent = ScriptedProvider()
        self.assertEqual(self.run_turn("hello?", silent).action, "skipped")
        self.assertEqual(silent.calls, [])

        # "Return to AI" resumes automatic replies.
        return_to_ai(self.conversation)
        self.assertEqual(self.run_turn("back", ScriptedProvider(text_response("Hi again"))).action, "replied")

    def test_burst_of_messages_answered_once(self, send):
        first = self.inbound("Hi")
        second = self.inbound("Do you deliver?")
        provider = ScriptedProvider(text_response("Yes, we deliver."))
        with self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(handle_incoming_message(first.id, provider=provider).action, "skipped")
            self.assertEqual(handle_incoming_message(second.id, provider=provider).action, "replied")
        self.assertEqual(provider.calls[0]["messages"], [{"role": "user", "content": "Hi\nDo you deliver?"}])

    @mock.patch("tools.executors.assert_public_url")
    @mock.patch("tools.executors.requests.post")
    def test_business_http_tool(self, post, _safe, send):
        tool = Tool.objects.create(
            business=self.business, name="check_order_status", description="Look up an order.",
            endpoint_url="https://shop.example.com/tools",
            input_schema={"type": "object", "properties": {"order_id": {"type": "string"}}},
        )
        post.return_value = SimpleNamespace(status_code=200, text='{"status": "shipped"}')
        provider = ScriptedProvider(
            tool_response("check_order_status", {"order_id": "1045"}),
            text_response("Order 1045 has shipped."),
        )
        self.run_turn("Where is order 1045?", provider)

        self.assertIn("check_order_status", provider.calls[0]["tools"])
        body = post.call_args.kwargs["data"]
        headers = post.call_args.kwargs["headers"]
        self.assertEqual(json.loads(body)["input"], {"order_id": "1045"})
        self.assertEqual(json.loads(body)["context"]["customer"]["phone_number"], "2348022222222")
        self.assertEqual(headers["X-Tool-Signature"], sign(tool.signing_secret, headers["X-Tool-Timestamp"], body))
        self.assertEqual(provider.calls[1]["messages"][-1]["content"][0]["content"], '{"status": "shipped"}')
        send.assert_called_once_with("2348022222222", "Order 1045 has shipped.")

    def test_http_tools_require_plan_feature(self, send):
        self.business.subscription.plan = Plan.objects.get(code="starter")
        self.business.subscription.save()
        Tool.objects.create(business=self.business, name="check_order_status", description="x",
                            endpoint_url="https://shop.example.com/tools")
        provider = ScriptedProvider(text_response("ok"))
        self.run_turn("hi", provider)
        self.assertNotIn("check_order_status", provider.calls[0]["tools"])

    def test_rag_context_is_injected(self, send):
        doc = KnowledgeDocument.objects.create(
            business=self.business, title="Policies", source_type="TEXT",
            raw_text="Check-in time is 2pm and check-out time is 11am.\n\nWe accept card payments.",
        )
        process_document(doc)
        provider = ScriptedProvider(text_response("Check-in is at 2pm."))
        self.run_turn("What time is check-in?", provider)
        content = provider.calls[0]["messages"][-1]["content"]
        self.assertIn("<business_knowledge>", content[0]["text"])
        self.assertIn("Check-in time is 2pm", content[0]["text"])
        self.assertEqual(content[1]["text"], "What time is check-in?")

    def test_refusal_sends_fallback(self, send):
        refused = text_response("", stop_reason="refusal")
        refused.refused = True
        self.run_turn("something", ScriptedProvider(refused))
        send.assert_called_once_with("2348022222222", self.business.ai_config.fallback_message)

    def test_quota_exhausted_hands_off(self, send):
        plan = self.business.subscription.plan
        plan.monthly_ai_responses = 0
        plan.save()
        outcome = self.run_turn("hi", ScriptedProvider())
        self.assertEqual(outcome.action, "handoff")
        send.assert_not_called()

    def test_long_reply_is_truncated_for_whatsapp(self, send):
        self.run_turn("essay please", ScriptedProvider(text_response("word " * 2000)))
        self.assertLessEqual(len(send.call_args.args[1]), 4096)

    def test_llm_failure_sends_fallback_and_escalates(self, send):
        message = self.inbound("hi")
        with mock.patch("chatbot.tasks.handle_incoming_message", side_effect=LLMError("bad request")):
            with self.captureOnCommitCallbacks(execute=True):
                process_incoming_message.delay(message.id)
        send.assert_called_once_with("2348022222222", self.business.ai_config.fallback_message)
        self.conversation.refresh_from_db()
        self.assertEqual(self.conversation.status, Conversation.Status.HUMAN_HANDLING)


class AnthropicProviderTests(TestCase):
    def make_response(self, content, stop_reason="end_turn"):
        return SimpleNamespace(
            content=content, stop_reason=stop_reason,
            usage=SimpleNamespace(input_tokens=10, output_tokens=5, cache_read_input_tokens=3),
        )

    def test_request_shape_for_opus_5(self):
        client = mock.MagicMock()
        client.beta.messages.create.return_value = self.make_response(
            [SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text="Hello")]
        )
        from tools.builtins import HANDOFF

        result = AnthropicProvider(client=client).create(
            model="claude-opus-5", system="sys", messages=[{"role": "user", "content": "hi"}],
            tools=[HANDOFF], max_tokens=4096, effort="low",
        )
        kwargs = client.beta.messages.create.call_args.kwargs
        self.assertEqual(kwargs["fallbacks"], "default")
        self.assertEqual(kwargs["betas"], ["server-side-fallback-2026-07-01"])
        self.assertEqual(kwargs["thinking"], {"type": "adaptive"})
        self.assertEqual(kwargs["output_config"], {"effort": "low"})
        self.assertEqual(kwargs["cache_control"], {"type": "ephemeral"})
        self.assertEqual(kwargs["tools"][0]["name"], "handoff_to_human")
        self.assertNotIn("temperature", kwargs)
        self.assertEqual(result.text, "Hello")
        # Thinking blocks are kept in the assistant turn for the tool loop.
        self.assertEqual(len(result.assistant_turn["content"]), 2)
        self.assertEqual(result.usage, {"input_tokens": 10, "output_tokens": 5, "cache_read_tokens": 3})

    def test_other_models_use_standard_endpoint(self):
        client = mock.MagicMock()
        client.messages.create.return_value = self.make_response([SimpleNamespace(type="text", text="ok")])
        AnthropicProvider(client=client).create(
            model="claude-haiku-4-5", system="s", messages=[], tools=[], max_tokens=1024,
        )
        kwargs = client.messages.create.call_args.kwargs
        self.assertNotIn("thinking", kwargs)
        self.assertNotIn("fallbacks", kwargs)
        client.beta.messages.create.assert_not_called()

    def test_mid_output_fallback_drops_declined_tool_calls(self):
        blocks = [
            SimpleNamespace(type="thinking", thinking=""),
            SimpleNamespace(type="text", text="Partial. "),
            SimpleNamespace(type="tool_use", id="t1", name="x", input={}),
            SimpleNamespace(type="fallback"),
            SimpleNamespace(type="text", text="Continued."),
        ]
        client = mock.MagicMock()
        client.beta.messages.create.return_value = self.make_response(blocks)
        result = AnthropicProvider(client=client).create(
            model="claude-opus-5", system="s", messages=[], tools=[], max_tokens=1024,
        )
        self.assertEqual(result.tool_calls, [])
        self.assertEqual(result.text, "Partial. Continued.")
        self.assertEqual([b.type for b in result.assistant_turn["content"]], ["text", "text"])


class MemoryTests(TestCase):
    def test_history_starts_with_user_and_skips_internal(self):
        business, _ = make_business()
        customer = get_or_create_customer(business, "234")
        conversation = get_active_conversation(business, customer)
        Message.objects.create(business=business, conversation=conversation, role="ASSISTANT",
                               direction="OUTBOUND", content="Welcome (template)", status="SENT")
        Message.objects.create(business=business, conversation=conversation, role="SYSTEM",
                               direction="INTERNAL", content="note", status="SENT")
        record_inbound(conversation, "hello")
        self.assertEqual(build_history(conversation, 20), [{"role": "user", "content": "hello"}])

    @override_settings(CHATBOT_LLM_PROVIDER="nope")
    def test_unknown_provider(self):
        from .llm import get_provider

        with self.assertRaises(LLMError):
            get_provider()
