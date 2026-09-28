from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.core.validators import validate_email
from django.db.models import Count, Q
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.utils import timezone
from django.views.decorators.http import require_POST

from analytics.views import OverviewView
from billing.services import get_usage
from conversations import services
from conversations.models import Channel, Conversation, Message
from customers.models import Customer
from knowledge.models import KnowledgeDocument
from tenants.models import Membership, Role
from whatsapp.models import MessageTemplate, WhatsAppAccount

from ..tenancy import member_required

STATUS_TABS = [
    ("active", "Active", Conversation.ACTIVE_STATUSES),
    ("HUMAN_HANDLING", "Needs human", [Conversation.Status.HUMAN_HANDLING]),
    ("AI_HANDLING", "AI", [Conversation.Status.AI_HANDLING, Conversation.Status.OPEN,
                           Conversation.Status.WAITING_FOR_CUSTOMER]),
    ("mine", "Assigned to me", None),
    ("RESOLVED", "Resolved", [Conversation.Status.RESOLVED, Conversation.Status.CLOSED]),
]


@member_required()
def overview(request):
    business = request.business
    usage = get_usage(business)
    counts = dict(
        Conversation.objects.filter(business=business).exclude(channel=Channel.SANDBOX)
        .values_list("status").annotate(n=Count("id")).values_list("status", "n")
    )
    subscription = getattr(business, "subscription", None)
    checklist = [
        ("Verify your email", request.user.email_verified, "dashboard:account"),
        ("Connect a WhatsApp number", WhatsAppAccount.objects.filter(business=business).exists(),
         "dashboard:whatsapp"),
        ("Configure your assistant", bool(business.ai_config.system_prompt), "dashboard:bot"),
        ("Add knowledge", KnowledgeDocument.objects.filter(business=business).exists(), "dashboard:knowledge"),
    ]
    return render(request, "dashboard/overview.html", {
        "usage": usage,
        "counts": counts,
        "needs_human": counts.get(Conversation.Status.HUMAN_HANDLING, 0),
        "subscription": subscription,
        "avg_first_response": OverviewView._avg_first_response(business),
        "checklist": checklist,
        "setup_done": all(done for _, done, _ in checklist),
        "recent": Conversation.objects.filter(business=business).exclude(channel=Channel.SANDBOX)
        .select_related("customer").order_by("-last_message_at")[:8],
    })


@member_required()
def inbox(request):
    tab = request.GET.get("tab", "active")
    qs = (Conversation.objects.filter(business=request.business).exclude(channel=Channel.SANDBOX)
          .select_related("customer", "assigned_agent"))
    statuses = next((s for key, _, s in STATUS_TABS if key == tab), None)
    if tab == "mine":
        qs = qs.filter(assigned_agent=request.user, status__in=Conversation.ACTIVE_STATUSES)
    elif statuses is not None:
        qs = qs.filter(status__in=statuses)
    search = request.GET.get("q", "").strip()
    if search:
        qs = qs.filter(Q(customer__name__icontains=search) | Q(customer__phone_number__icontains=search))
    page = Paginator(qs.order_by("-last_message_at"), 30).get_page(request.GET.get("page"))
    return render(request, "dashboard/inbox.html", {"page": page, "tab": tab, "tabs": STATUS_TABS, "q": search})


def _conversation(request, pk):
    return get_object_or_404(
        Conversation.objects.select_related("customer", "assigned_agent", "whatsapp_account"),
        business=request.business, pk=pk,
    )


def _thread(conversation, after=0):
    return conversation.messages.filter(id__gt=after).select_related("sender").order_by("id")


@member_required()
def conversation(request, pk):
    conv = _conversation(request, pk)
    templates = MessageTemplate.objects.filter(business=request.business, status="APPROVED")
    if conv.whatsapp_account_id:
        templates = templates.filter(whatsapp_account_id=conv.whatsapp_account_id)
    agents = [m for m in Membership.objects.filter(business=request.business).select_related("user")
              if m.has_role(Role.AGENT)]
    thread = list(_thread(conv))
    return render(request, "dashboard/conversation.html", {
        "conv": conv,
        "thread": thread,
        "last_id": thread[-1].id if thread else 0,
        "templates": [t for t in templates if t.is_sendable],
        "agents": agents,
        "window_open": conv.service_window_open,
        "history": Conversation.objects.filter(business=request.business, customer=conv.customer)
        .exclude(pk=conv.pk).order_by("-started_at")[:5],
    })


@member_required()
def conversation_poll(request, pk):
    """New messages since ``after`` as HTML, plus the current status (used for live updates)."""
    conv = _conversation(request, pk)
    try:
        after = int(request.GET.get("after", 0))
    except ValueError:
        after = 0
    thread = list(_thread(conv, after))
    # Status changes of earlier outbound messages (sent -> delivered -> read).
    statuses = dict(conv.messages.filter(direction=Message.Direction.OUTBOUND).values_list("id", "status"))
    html = render_to_string("dashboard/_messages.html", {"thread": thread}, request=request)
    return JsonResponse({
        "html": html, "last_id": thread[-1].id if thread else after, "status": conv.get_status_display(),
        "status_code": conv.status, "statuses": statuses,
    })


@member_required(Role.AGENT)
@require_POST
def conversation_action(request, pk, action):
    conv = _conversation(request, pk)
    user = request.user
    if action == "reply":
        content = request.POST.get("content", "").strip()
        if not content:
            messages.error(request, "Type a message first.")
        elif len(content) > 4096:
            messages.error(request, "Messages are limited to 4096 characters.")
        else:
            try:
                services.agent_reply(conv, content, user)
            except services.ServiceWindowClosed as exc:
                messages.error(request, str(exc))
    elif action == "template":
        template = MessageTemplate.objects.filter(business=request.business, pk=request.POST.get("template")).first()
        params = [p.strip() for p in request.POST.getlist("params")][:20]
        try:
            if template is None:
                raise ValueError("Choose a template.")
            params = params[:template.parameter_count]
            services.send_template_message(conv, template, params, sender=user)
            messages.success(request, "Template sent.")
        except ValueError as exc:
            messages.error(request, str(exc))
    elif action == "takeover":
        services.handoff_to_human(conv, reason=f"Taken over by {user.email}.", actor=user)
        messages.success(request, "You're handling this conversation. The AI is paused.")
    elif action == "return":
        services.return_to_ai(conv, actor=user)
        messages.success(request, "The AI assistant is handling this conversation again.")
    elif action == "resolve":
        services.resolve(conv, actor=user)
        messages.success(request, "Conversation resolved.")
    elif action == "assign":
        membership = Membership.objects.filter(business=request.business, user_id=request.POST.get("user")).first()
        if membership and membership.has_role(Role.AGENT):
            conv.assigned_agent = membership.user
            conv.save(update_fields=["assigned_agent", "updated_at"])
            messages.success(request, f"Assigned to {membership.user.email}.")
        else:
            messages.error(request, "Choose a team member.")
    else:
        raise Http404
    return redirect("dashboard:conversation", conv.pk)


@member_required(Role.AGENT)
def new_conversation(request):
    accounts = WhatsAppAccount.objects.filter(business=request.business, status=WhatsAppAccount.Status.ACTIVE)
    templates = [t for t in MessageTemplate.objects.filter(business=request.business, status="APPROVED")
                 if t.is_sendable]
    if request.method == "POST":
        account = accounts.filter(pk=request.POST.get("account")).first()
        template = next((t for t in templates if str(t.pk) == request.POST.get("template")), None)
        phone = request.POST.get("phone", "").strip().lstrip("+").replace(" ", "")
        try:
            if account is None or template is None:
                raise ValueError("Choose a number and a template.")
            if not phone.isdigit() or not 7 <= len(phone) <= 15:
                raise ValueError("Enter the phone number in international format, e.g. +2348012345678.")
            params = request.POST.getlist("params")[:template.parameter_count]
            message = services.start_conversation(
                request.business, account, phone, template, params, sender=request.user,
                name=request.POST.get("name", "").strip()[:200],
            )
        except ValueError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "Message sent.")
            return redirect("dashboard:conversation", message.conversation_id)
    return render(request, "dashboard/new_conversation.html", {"accounts": accounts, "templates": templates})


@member_required()
def message_media(request, pk):
    message = get_object_or_404(Message, business=request.business, pk=pk)
    if not message.media:
        raise Http404
    return FileResponse(message.media.open("rb"), content_type=message.media_mime_type or None)


@member_required()
def customers(request):
    qs = Customer.objects.filter(business=request.business).exclude(phone_number__startswith="sandbox-")
    search = request.GET.get("q", "").strip()
    if search:
        qs = qs.filter(Q(name__icontains=search) | Q(phone_number__icontains=search) | Q(email__icontains=search))
    qs = qs.annotate(conversation_count=Count("conversations")).order_by("-updated_at")
    page = Paginator(qs, 50).get_page(request.GET.get("page"))
    return render(request, "dashboard/customers.html", {"page": page, "q": search})


@member_required()
def customer(request, pk):
    obj = get_object_or_404(Customer, business=request.business, pk=pk)
    if request.method == "POST":
        if not request.membership.has_role(Role.AGENT):
            raise PermissionDenied
        email = request.POST.get("email", "").strip()[:254]
        try:
            if email:
                validate_email(email)
        except ValidationError:
            messages.error(request, "Enter a valid email address.")
            return redirect("dashboard:customer", obj.pk)
        obj.name = request.POST.get("name", "").strip()[:200]
        obj.email = email
        obj.external_id = request.POST.get("external_id", "").strip()[:128]
        obj.metadata = {**obj.metadata, "notes": request.POST.get("notes", "")[:5000]}
        obj.save()
        messages.success(request, "Customer saved.")
        return redirect("dashboard:customer", obj.pk)
    return render(request, "dashboard/customer.html", {
        "customer": obj,
        "conversations": obj.conversations.order_by("-started_at")[:20],
        "now": timezone.now(),
    })
