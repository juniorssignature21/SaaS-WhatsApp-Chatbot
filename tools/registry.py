"""Assemble the tool set available to a business's assistant."""

import json
import logging

from billing.services import has_feature

from . import builtins
from .base import ToolResult
from .executors import http_tool_spec
from .models import Tool

logger = logging.getLogger(__name__)


def get_tools(business, ai_config):
    specs = [builtins.GET_CUSTOMER_PROFILE, builtins.UPDATE_CUSTOMER_PROFILE]
    if ai_config.human_handoff_enabled:
        specs.append(builtins.HANDOFF)
    if has_feature(business, "tools"):
        for tool in Tool.objects.filter(business=business, enabled=True).order_by("name"):
            if tool.name in builtins.BUILTIN_NAMES:
                continue
            specs.append(http_tool_spec(tool))
    return specs


def run_tool(specs, name, args, ctx):
    spec = next((s for s in specs if s.name == name), None)
    if spec is None:
        return ToolResult(f"Unknown tool {name!r}.", is_error=True)
    if not isinstance(args, dict):
        return ToolResult("Tool input must be a JSON object.", is_error=True)
    try:
        return spec.handler(ctx, args)
    except Exception:  # noqa: BLE001 - a broken tool must not kill the reply
        logger.exception("Tool %s failed for business %s", name, ctx.business.id)
        return ToolResult(f"The {name} tool failed unexpectedly.", is_error=True)


def describe_args(args):
    return json.dumps(args, ensure_ascii=False)[:500]
