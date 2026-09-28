"""Team, billing, business settings, API keys, account security, audit, notifications."""

import segno
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import password_validation, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts import services as account_services
from accounts import totp
from billing import paystack
from billing.models import Payment, Plan
from billing.services import cancel_subscription, confirm_payment, get_usage, start_checkout
from notifications.models import Notification
from tenants.models import APIKey, AuditLog, Membership, Role
from tenants.serializers import BusinessSerializer, InviteMemberSerializer
from tenants.services import audit, create_business

from ..tenancy import SESSION_KEY, get_membership, member_required
from .common import error_redirect, post_data

# --- Business switching / creation ------------------------------------------


@login_required
@require_POST
def switch_business(request, pk):
    membership = Membership.objects.filter(user=request.user, business_id=pk).first()
    if membership is None:
        raise PermissionDenied
    request.session[SESSION_KEY] = membership.business_id
    return redirect("dashboard:overview")


@login_required
def create_business_view(request):
    if request.method == "POST":
        name = request.POST.get("name", "").strip()[:200]
        if not name:
            messages.error(request, "Enter a business name.")
        else:
            business = create_business(owner=request.user, name=name)
            request.session[SESSION_KEY] = business.id
            messages.success(request, f"{business.name} created.")
            return redirect("dashboard:overview")
    return render(request, "dashboard/create_business.html", {"has_business": get_membership(request) is not None})


# --- Team ---------------------------------------------------------------------


@member_required()
def team(request):
    return render(request, "dashboard/team.html", {
        "members": Membership.objects.filter(business=request.business).select_related("user").order_by("created_at"),
        "roles": [r for r in Role if r != Role.OWNER],
    })


def _check_can_grant(request, role):
    if role == Role.ADMIN and not request.membership.has_role(Role.OWNER):
        raise PermissionDenied


@member_required(Role.ADMIN)
@require_POST
def team_invite(request):
    serializer = InviteMemberSerializer(data=post_data(request, "email", "role"))
    if not serializer.is_valid():
        return error_redirect(request, serializer.errors, "dashboard:team")
    user, role = serializer.validated_data["email"], serializer.validated_data["role"]
    _check_can_grant(request, role)
    membership, created = Membership.objects.get_or_create(user=user, business=request.business,
                                                           defaults={"role": role})
    if created:
        audit(request.business, request.user, "team.member_added", membership, request, role=role)
        messages.success(request, f"{user.email} added as {role.lower()}.")
    else:
        messages.error(request, "That person is already a member.")
    return redirect("dashboard:team")


@member_required(Role.ADMIN)
@require_POST
def team_member(request, pk, action):
    membership = get_object_or_404(Membership, business=request.business, pk=pk)
    if membership.role == Role.OWNER:
        messages.error(request, "The owner cannot be changed here.")
        return redirect("dashboard:team")
    _check_can_grant(request, membership.role)
    if action == "role":
        role = request.POST.get("role")
        if role not in {Role.ADMIN, Role.AGENT, Role.VIEWER}:
            messages.error(request, "Choose a role.")
            return redirect("dashboard:team")
        _check_can_grant(request, role)
        membership.role = role
        membership.save(update_fields=["role", "updated_at"])
        audit(request.business, request.user, "team.role_changed", membership, request, role=role)
        messages.success(request, "Role updated.")
    elif action == "remove":
        audit(request.business, request.user, "team.member_removed", membership, request, email=membership.user.email)
        membership.delete()
        messages.success(request, "Member removed.")
    return redirect("dashboard:team")


# --- Billing ------------------------------------------------------------------


@member_required(Role.ADMIN)
def billing(request):
    return render(request, "dashboard/billing.html", {
        "subscription": request.business.subscription,
        "plans": Plan.objects.filter(is_public=True).order_by("price"),
        "usage": get_usage(request.business),
        "payments": Payment.objects.filter(business=request.business).select_related("plan")[:20],
        "payments_enabled": bool(settings.PAYSTACK_SECRET_KEY),
    })


@member_required(Role.OWNER)
@require_POST
def billing_checkout(request, code):
    plan = get_object_or_404(Plan, code=code, is_public=True)
    callback = request.build_absolute_uri(reverse("dashboard:billing_callback"))
    try:
        url, _ = start_checkout(request.business, plan, request.user.email, callback)
    except paystack.PaystackError as exc:
        messages.error(request, str(exc))
        return redirect("dashboard:billing")
    return redirect(url)


@member_required(Role.ADMIN)
def billing_callback(request):
    reference = request.GET.get("reference", "")
    if not Payment.objects.filter(business=request.business, reference=reference).exists():
        messages.error(request, "Unknown payment reference.")
        return redirect("dashboard:billing")
    try:
        payment = confirm_payment(reference)
    except paystack.PaystackError as exc:
        messages.error(request, f"We couldn't confirm the payment yet: {exc}")
        return redirect("dashboard:billing")
    if payment.status == Payment.Status.SUCCESS:
        messages.success(request, f"Payment received. You're on the {payment.plan.name} plan.")
    else:
        messages.error(request, "The payment was not completed.")
    return redirect("dashboard:billing")


@member_required(Role.OWNER)
@require_POST
def billing_cancel(request):
    try:
        cancel_subscription(request.business)
        messages.success(request, "Renewal cancelled. Your plan stays active until the end of the period.")
    except paystack.PaystackError as exc:
        messages.error(request, str(exc))
    return redirect("dashboard:billing")


# --- Business settings and API keys -------------------------------------------


@member_required(Role.ADMIN)
def business_settings(request):
    if request.method == "POST":
        data = post_data(request, "name", "email", "phone", "timezone", "brand_name", "brand_color")
        serializer = BusinessSerializer(request.business, data=data, partial=True)
        if not serializer.is_valid():
            return error_redirect(request, serializer.errors, "dashboard:settings")
        serializer.save()
        audit(request.business, request.user, "business.updated", request.business, request,
              fields=sorted(serializer.validated_data))
        messages.success(request, "Settings saved.")
        return redirect("dashboard:settings")
    return render(request, "dashboard/settings.html", {
        "api_keys": APIKey.objects.filter(business=request.business, revoked_at__isnull=True),
        "new_key": request.session.pop("new_api_key", None),
        "api_available": request.business.subscription.plan.has_feature("api_access"),
        "key_roles": APIKey.ROLE_CHOICES,
    })


@member_required(Role.ADMIN)
@require_POST
def api_key_create(request):
    name = request.POST.get("name", "").strip()[:100]
    role = request.POST.get("role", Role.AGENT)
    if not name or role not in {Role.ADMIN, Role.AGENT, Role.VIEWER}:
        messages.error(request, "Give the key a name and a role.")
        return redirect("dashboard:settings")
    _check_can_grant(request, role)
    key, raw = APIKey.issue(request.business, name, role=role, created_by=request.user)
    audit(request.business, request.user, "api_key.created", key, request, name=name, role=role)
    request.session["new_api_key"] = raw  # shown once, then discarded
    return redirect("dashboard:settings")


@member_required(Role.ADMIN)
@require_POST
def api_key_revoke(request, pk):
    key = get_object_or_404(APIKey, business=request.business, pk=pk, revoked_at__isnull=True)
    key.revoke()
    audit(request.business, request.user, "api_key.revoked", key, request, name=key.name)
    messages.success(request, "API key revoked.")
    return redirect("dashboard:settings")


# --- Personal account -----------------------------------------------------------


@member_required()
def account(request):
    user = request.user
    if request.method == "POST":
        section = request.POST.get("section")
        if section == "profile":
            user.full_name = request.POST.get("full_name", "").strip()[:200]
            user.save(update_fields=["full_name"])
            request.membership.notify_by_email = "notify_by_email" in request.POST
            request.membership.save(update_fields=["notify_by_email", "updated_at"])
            messages.success(request, "Profile saved.")
        elif section == "password":
            if not user.check_password(request.POST.get("current_password", "")):
                messages.error(request, "Your current password is incorrect.")
            else:
                try:
                    password_validation.validate_password(request.POST.get("new_password", ""), user)
                except ValidationError as exc:
                    for error in exc.messages:
                        messages.error(request, error)
                else:
                    user.set_password(request.POST["new_password"])
                    user.save(update_fields=["password"])
                    update_session_auth_hash(request, user)
                    messages.success(request, "Password changed.")
        elif section == "resend":
            account_services.send_verification_email(user)
            messages.success(request, "Verification email sent.")
        elif section == "mfa_disable":
            try:
                account_services.disable_mfa(user, request.POST.get("code", ""))
                messages.success(request, "Two-factor authentication is off.")
            except account_services.AccountError as exc:
                messages.error(request, str(exc))
        return redirect("dashboard:account")
    return render(request, "dashboard/account.html", {"recovery_codes": request.session.pop("recovery_codes", None)})


@member_required()
def mfa_setup(request):
    user = request.user
    if user.mfa_enabled:
        return redirect("dashboard:account")
    if request.method == "POST":
        try:
            codes = account_services.enable_mfa(user, request.POST.get("code", ""))
        except account_services.AccountError as exc:
            messages.error(request, str(exc))
        else:
            request.session["recovery_codes"] = codes
            messages.success(request, "Two-factor authentication is on. Save your recovery codes now.")
            return redirect("dashboard:account")
    if user.mfa_secret and "restart" not in request.GET:
        # Keep the secret the user may already have scanned.
        secret = user.mfa_secret
        uri = totp.provisioning_uri(secret, user.email, settings.PLATFORM_NAME)
    else:
        secret, uri = account_services.begin_mfa_setup(user)
    qr_svg = segno.make(uri, error="m").svg_inline(scale=5, dark="#111827")
    return render(request, "dashboard/mfa_setup.html", {"secret": secret, "qr_svg": qr_svg})


# --- Audit and notifications -------------------------------------------------------


@member_required(Role.ADMIN)
def audit_log(request):
    qs = AuditLog.objects.filter(business=request.business).select_related("actor")
    return render(request, "dashboard/audit.html", {"page": Paginator(qs, 50).get_page(request.GET.get("page"))})


@member_required()
def notifications(request):
    qs = Notification.objects.filter(user=request.user, business=request.business).select_related("conversation")
    if request.method == "POST":
        qs.filter(read_at__isnull=True).update(read_at=timezone.now())
        return redirect("dashboard:notifications")
    page = Paginator(qs, 30).get_page(request.GET.get("page"))
    return render(request, "dashboard/notifications.html", {"page": page})


@member_required()
def notification_open(request, pk):
    notification = get_object_or_404(Notification, user=request.user, business=request.business, pk=pk)
    if notification.read_at is None:
        notification.read_at = timezone.now()
        notification.save(update_fields=["read_at"])
    if notification.conversation_id:
        return redirect("dashboard:conversation", notification.conversation_id)
    return redirect("dashboard:notifications")
