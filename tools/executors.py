"""Execute business-defined HTTP tools.

Request sent to the business endpoint (POST; GET sends ``input`` as query params):

    {"tool": "check_order_status", "input": {...},
     "context": {"business_id": 1, "conversation_id": 2,
                 "customer": {"phone_number": "...", "name": "...", "external_id": "..."}}}

Headers: ``X-Tool-Signature: sha256=<hex HMAC of the raw body with the tool's signing secret>``
and ``X-Tool-Timestamp``; the business should verify both.
"""

import hashlib
import hmac
import json
import time

import requests

from common.netsafety import UnsafeURLError, assert_public_url

from .base import ToolResult, ToolSpec

MAX_RESULT_CHARS = 8000


def sign(secret, timestamp, body):
    message = f"{timestamp}.".encode() + body
    return "sha256=" + hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def execute_http_tool(tool, ctx, args):
    try:
        assert_public_url(tool.endpoint_url)
    except UnsafeURLError as exc:
        return ToolResult(f"Tool misconfigured: {exc}", is_error=True)

    customer = ctx.customer
    payload = {
        "tool": tool.name,
        "input": args,
        "context": {
            "business_id": ctx.business.id,
            "conversation_id": ctx.conversation.id,
            "customer": {
                "phone_number": customer.phone_number,
                "name": customer.name,
                "external_id": customer.external_id,
            },
        },
    }
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    timestamp = str(int(time.time()))
    headers = {
        "Content-Type": "application/json",
        "X-Tool-Timestamp": timestamp,
        "X-Tool-Signature": sign(tool.signing_secret, timestamp, body),
    }
    try:
        if tool.http_method == "GET":
            response = requests.get(
                tool.endpoint_url, params={k: v for k, v in args.items() if isinstance(v, (str, int, float))},
                headers=headers, timeout=tool.timeout_seconds, allow_redirects=False,
            )
        else:
            response = requests.post(
                tool.endpoint_url, data=body, headers=headers,
                timeout=tool.timeout_seconds, allow_redirects=False,
            )
    except requests.RequestException as exc:
        return ToolResult(f"The {tool.name} service is unavailable ({exc.__class__.__name__}).", is_error=True)

    text = response.text[:MAX_RESULT_CHARS]
    if response.status_code >= 400:
        return ToolResult(f"The {tool.name} service returned HTTP {response.status_code}: {text}", is_error=True)
    return ToolResult(text or "(empty response)")


def http_tool_spec(tool):
    schema = tool.input_schema or {}
    if schema.get("type") != "object":
        schema = {"type": "object", "properties": {}}
    return ToolSpec(
        name=tool.name,
        description=tool.description,
        input_schema=schema,
        handler=lambda ctx, args, _tool=tool: execute_http_tool(_tool, ctx, args),
    )
