"""Tools provided by the platform to every business."""

from conversations.services import handoff_to_human

from .base import ToolResult, ToolSpec


def _handoff(ctx, args):
    reason = str(args.get("reason", ""))[:500]
    handoff_to_human(ctx.conversation, reason=reason)
    ctx.effects["handoff"] = True
    return ToolResult("The conversation has been transferred to a human agent. "
                      "Tell the customer a team member will reply shortly.")


def _get_profile(ctx, args):
    c = ctx.customer
    return ToolResult(
        f"name: {c.name or 'unknown'}\nphone: {c.phone_number}\nemail: {c.email or 'unknown'}"
    )


def _update_profile(ctx, args):
    c = ctx.customer
    fields = []
    if args.get("name"):
        c.name = str(args["name"])[:200]
        fields.append("name")
    if args.get("email"):
        from django.core.exceptions import ValidationError
        from django.core.validators import validate_email

        try:
            validate_email(args["email"])
        except ValidationError:
            return ToolResult("That email address is not valid.", is_error=True)
        c.email = args["email"]
        fields.append("email")
    if not fields:
        return ToolResult("Nothing to update.", is_error=True)
    c.save(update_fields=[*fields, "updated_at"])
    return ToolResult(f"Updated customer {', '.join(fields)}.")


HANDOFF = ToolSpec(
    name="handoff_to_human",
    description=(
        "Transfer the conversation to a human team member. Use when the customer asks for a person, "
        "is upset or complaining, or needs something you cannot do with your knowledge and tools."
    ),
    input_schema={
        "type": "object",
        "properties": {"reason": {"type": "string", "description": "Short reason for the handoff."}},
        "required": ["reason"],
    },
    handler=_handoff,
)

GET_CUSTOMER_PROFILE = ToolSpec(
    name="get_customer_profile",
    description="Look up what the business knows about the customer you are chatting with.",
    input_schema={"type": "object", "properties": {}},
    handler=_get_profile,
)

UPDATE_CUSTOMER_PROFILE = ToolSpec(
    name="update_customer_profile",
    description="Save the customer's name and/or email address when they tell you.",
    input_schema={
        "type": "object",
        "properties": {"name": {"type": "string"}, "email": {"type": "string"}},
    },
    handler=_update_profile,
)

BUILTIN_NAMES = {HANDOFF.name, GET_CUSTOMER_PROFILE.name, UPDATE_CUSTOMER_PROFILE.name}
