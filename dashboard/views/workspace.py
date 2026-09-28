import re

from django.contrib import messages
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from billing.services import has_feature
from chatbot import playground
from chatbot.llm import LLMError
from chatbot.models import AIConfiguration
from chatbot.serializers import AIConfigurationSerializer
from chatbot.templates import TEMPLATES, apply_template
from knowledge.models import KnowledgeDocument
from knowledge.retrieval import search
from knowledge.serializers import KnowledgeDocumentSerializer
from knowledge.services import DocumentLimitReached, assert_can_add_document
from knowledge.tasks import process_knowledge_document
from tenants.models import Role
from tenants.services import audit
from tools.builtins import BUILTIN_NAMES
from tools.models import Tool, generate_signing_secret
from tools.serializers import ToolSerializer
from whatsapp.client import WhatsAppAPIError, WhatsAppClient
from whatsapp.models import MessageTemplate, WhatsAppAccount
from whatsapp.serializers import WhatsAppAccountSerializer
from whatsapp.services import ConnectNotAllowed, assert_can_connect, sync_templates

from ..tenancy import member_required
from .common import error_redirect, flatten_errors, post_data

# --- WhatsApp -----------------------------------------------------------------


@member_required(Role.ADMIN)
def whatsapp(request):
    accounts = WhatsAppAccount.objects.filter(business=request.business).order_by("created_at")
    if request.method == "POST":
        try:
            assert_can_connect(request.business, request.user)
        except ConnectNotAllowed as exc:
            messages.error(request, str(exc))
            return redirect("dashboard:whatsapp")
        data = post_data(request, "display_name", "phone_number", "phone_number_id", "business_account_id",
                         "access_token")
        serializer = WhatsAppAccountSerializer(data=data)
        if not serializer.is_valid():
            return error_redirect(request, serializer.errors, "dashboard:whatsapp")
        account = serializer.save(business=request.business)
        audit(request.business, request.user, "whatsapp.connected", account, request,
              phone_number=account.phone_number)
        messages.success(request, "Number connected. Verify it and sync your templates below.")
        return redirect("dashboard:whatsapp")
    return render(request, "dashboard/whatsapp.html", {
        "accounts": accounts,
        "templates": MessageTemplate.objects.filter(business=request.business).select_related("whatsapp_account"),
        "webhook_url": request.build_absolute_uri("/webhooks/whatsapp/"),
    })


@member_required(Role.ADMIN)
@require_POST
def whatsapp_action(request, pk, action):
    account = get_object_or_404(WhatsAppAccount, business=request.business, pk=pk)
    try:
        if action == "verify":
            info = WhatsAppClient(account).get_phone_number_info()
            if info.get("verified_name") and not account.display_name:
                account.display_name = info["verified_name"]
                account.save(update_fields=["display_name", "updated_at"])
            messages.success(request, f"Connected: {info.get('verified_name', '')} "
                                      f"{info.get('display_phone_number', '')} "
                                      f"(quality {info.get('quality_rating', 'n/a')}).")
        elif action == "sync":
            count = sync_templates(account)
            messages.success(request, f"Synced {count} template(s).")
        elif action == "token":
            token = request.POST.get("access_token", "").strip()
            if not token:
                messages.error(request, "Paste the new access token.")
            else:
                account.access_token = token
                account.save(update_fields=["access_token", "updated_at"])
                audit(request.business, request.user, "whatsapp.updated", account, request, token_rotated=True)
                messages.success(request, "Access token updated.")
        elif action == "toggle":
            account.status = (WhatsAppAccount.Status.DISABLED if account.status == WhatsAppAccount.Status.ACTIVE
                              else WhatsAppAccount.Status.ACTIVE)
            account.save(update_fields=["status", "updated_at"])
            messages.success(request, f"Number {account.get_status_display().lower()}.")
        elif action == "delete":
            audit(request.business, request.user, "whatsapp.disconnected", account, request,
                  phone_number=account.phone_number)
            account.delete()
            messages.success(request, "Number disconnected.")
    except WhatsAppAPIError as exc:
        messages.error(request, f"WhatsApp said: {exc}")
    return redirect("dashboard:whatsapp")


# --- Assistant ----------------------------------------------------------------

AI_FIELDS = ("name", "system_prompt", "model", "max_tokens", "effort", "language", "welcome_message",
             "fallback_message", "history_limit")
AI_BOOLEANS = ("enabled", "human_handoff_enabled", "rag_enabled", "memory_enabled")


@member_required()
def bot(request):
    config = request.business.ai_config
    if request.method == "POST":
        if not request.membership.has_role(Role.ADMIN):
            messages.error(request, "Only admins can change the assistant.")
            return redirect("dashboard:bot")
        data = post_data(request, *AI_FIELDS, booleans=AI_BOOLEANS)
        serializer = AIConfigurationSerializer(config, data=data, partial=True)
        if not serializer.is_valid():
            return error_redirect(request, serializer.errors, "dashboard:bot")
        serializer.save()
        audit(request.business, request.user, "chatbot.settings_updated", config, request,
              fields=sorted(serializer.validated_data))
        messages.success(request, "Assistant settings saved.")
        return redirect("dashboard:bot")
    return render(request, "dashboard/bot.html", {
        "config": config,
        "templates": TEMPLATES,
        "effort_choices": AIConfiguration.Effort.choices,
        "models": ["claude-opus-5", "claude-sonnet-5", "claude-haiku-4-5"],
    })


@member_required(Role.ADMIN)
@require_POST
def bot_template(request, key):
    if key not in TEMPLATES:
        messages.error(request, "Unknown template.")
        return redirect("dashboard:bot")
    config = apply_template(request.business.ai_config, key)
    config.save()
    audit(request.business, request.user, "chatbot.template_applied", config, request, template=key)
    tools = ", ".join(TEMPLATES[key]["suggested_tools"])
    messages.success(request, f"Applied the {TEMPLATES[key]['name']} template. Review the instructions, "
                              f"then connect tools such as {tools} under Tools.")
    return redirect("dashboard:bot")


@member_required(Role.AGENT)
def bot_playground(request):
    key = str(request.user.pk)
    if request.method == "POST":
        if "reset" in request.POST:
            playground.reset(request.business, key)
        else:
            text = request.POST.get("message", "").strip()[:4000]
            if text:
                try:
                    _, outcome = playground.chat(request.business, key, text)
                    if outcome.action == "skipped":
                        messages.info(request, f"The assistant did not reply: {outcome.reason}.")
                except LLMError as exc:
                    messages.error(request, f"The AI provider failed: {exc}")
        return redirect("dashboard:bot_playground")
    conversation = playground.playground_conversation(request.business, key)
    return render(request, "dashboard/playground.html", {
        "thread": conversation.messages.order_by("id").select_related("sender"),
        "config": request.business.ai_config,
    })


# --- Knowledge ----------------------------------------------------------------


def _parse_faqs(text):
    """'Q: ...' / 'A: ...' blocks -> [{"question", "answer"}]."""
    items = []
    for block in re.split(r"\n\s*\n", text.strip()):
        match = re.match(r"^\s*Q:\s*(.+?)\s*\n\s*A:\s*(.+)$", block, re.S | re.I)
        if match:
            items.append({"question": match.group(1).strip(), "answer": match.group(2).strip()})
    return items


@member_required()
def knowledge(request):
    documents = KnowledgeDocument.objects.filter(business=request.business).order_by("-created_at")
    if request.method == "POST":
        if not request.membership.has_role(Role.ADMIN):
            messages.error(request, "Only admins can change the knowledge base.")
            return redirect("dashboard:knowledge")
        try:
            assert_can_add_document(request.business)
        except DocumentLimitReached as exc:
            messages.error(request, str(exc))
            return redirect("dashboard:knowledge")
        source = request.POST.get("source_type", "")
        data = {"title": request.POST.get("title", "").strip(), "source_type": source}
        if source == KnowledgeDocument.SourceType.URL:
            data.update(source_url=request.POST.get("source_url", "").strip(),
                        max_pages=request.POST.get("max_pages") or 1)
        elif source == KnowledgeDocument.SourceType.FAQ:
            data["faqs"] = _parse_faqs(request.POST.get("faq_text", ""))
        elif source == KnowledgeDocument.SourceType.TEXT:
            data["raw_text"] = request.POST.get("raw_text", "")
        elif source == KnowledgeDocument.SourceType.FILE:
            data["file"] = request.FILES.get("file")
        if not data["title"]:
            data["title"] = (data.get("source_url") or getattr(data.get("file"), "name", "") or "Untitled")[:255]
        serializer = KnowledgeDocumentSerializer(data=data)
        if not serializer.is_valid():
            return error_redirect(request, serializer.errors, "dashboard:knowledge")
        with transaction.atomic():
            document = serializer.save(business=request.business)
            audit(request.business, request.user, "knowledge.document_added", document, request)
            transaction.on_commit(lambda: process_knowledge_document.delay(document.id))
        messages.success(request, "Added. Processing usually takes a few seconds.")
        return redirect("dashboard:knowledge")

    results, query = None, request.GET.get("q", "").strip()
    if query:
        results = search(request.business, query)
    return render(request, "dashboard/knowledge.html", {
        "documents": documents, "results": results, "q": query,
        "rag_available": has_feature(request.business, "rag"),
    })


@member_required(Role.ADMIN)
@require_POST
def knowledge_action(request, pk, action):
    document = get_object_or_404(KnowledgeDocument, business=request.business, pk=pk)
    if action == "reprocess":
        process_knowledge_document.delay(document.id)
        messages.success(request, "Reprocessing started.")
    elif action == "toggle":
        document.enabled = not document.enabled
        document.save(update_fields=["enabled", "updated_at"])
        messages.success(request, "Document " + ("enabled." if document.enabled else "disabled."))
    elif action == "delete":
        audit(request.business, request.user, "knowledge.document_deleted", document, request, title=document.title)
        if document.file:
            document.file.delete(save=False)
        document.delete()
        messages.success(request, "Document deleted.")
    return redirect("dashboard:knowledge")


# --- Tools --------------------------------------------------------------------

TOOL_FIELDS = ("name", "description", "endpoint_url", "http_method", "timeout_seconds")


@member_required(Role.ADMIN)
def tools(request):
    return render(request, "dashboard/tools.html", {
        "tools": Tool.objects.filter(business=request.business).order_by("name"),
        "tools_available": has_feature(request.business, "tools"),
        "builtins": sorted(BUILTIN_NAMES),
    })


@member_required(Role.ADMIN)
def tool_form(request, pk=None):
    tool = get_object_or_404(Tool, business=request.business, pk=pk) if pk else None
    if request.method == "POST":
        data = post_data(request, *TOOL_FIELDS, booleans=("enabled",), json_fields=("input_schema",))
        if data.get("input_schema") == "__invalid_json__":
            messages.error(request, "The input schema is not valid JSON.")
            return render(request, "dashboard/tool_form.html", {"tool": tool, "values": request.POST})
        serializer = ToolSerializer(tool, data=data, context={"business": request.business}, partial=tool is not None)
        if serializer.is_valid():
            saved = serializer.save(business=request.business)
            audit(request.business, request.user, "tool.updated" if tool else "tool.created", saved, request,
                  name=saved.name)
            messages.success(request, "Tool saved.")
            return redirect("dashboard:tool_edit", saved.pk)
        for error in flatten_errors(serializer.errors):
            messages.error(request, error)
        return render(request, "dashboard/tool_form.html", {"tool": tool, "values": request.POST})
    return render(request, "dashboard/tool_form.html", {"tool": tool, "values": None})


@member_required(Role.ADMIN)
@require_POST
def tool_action(request, pk, action):
    tool = get_object_or_404(Tool, business=request.business, pk=pk)
    if action == "rotate":
        tool.signing_secret = generate_signing_secret()
        tool.save(update_fields=["signing_secret", "updated_at"])
        audit(request.business, request.user, "tool.secret_rotated", tool, request)
        messages.success(request, "Signing secret rotated. Update your endpoint.")
        return redirect("dashboard:tool_edit", tool.pk)
    if action == "delete":
        audit(request.business, request.user, "tool.deleted", tool, request, name=tool.name)
        tool.delete()
        messages.success(request, "Tool deleted.")
    return redirect("dashboard:tools")
