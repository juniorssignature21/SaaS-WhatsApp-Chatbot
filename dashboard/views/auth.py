import time

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, password_validation
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods, require_POST

from accounts import services as account_services
from accounts.models import User
from accounts.serializers import SignupSerializer
from tenants.services import create_business

from ..tenancy import SESSION_KEY
from .common import flatten_errors

MFA_SESSION_KEY = "mfa_pending_user"
MAX_ATTEMPTS = 10
ATTEMPT_WINDOW = 600


def _too_many_attempts(request, scope, identifier=""):
    """Simple brute-force guard: N failures per IP (+identifier) per window."""
    key = f"dashboard-auth:{scope}:{request.META.get('REMOTE_ADDR', '')}:{identifier}"
    return cache.get(key, 0) >= MAX_ATTEMPTS, key


def _record_failure(key):
    if not cache.add(key, 1, ATTEMPT_WINDOW):
        try:
            cache.incr(key)
        except ValueError:
            cache.set(key, 1, ATTEMPT_WINDOW)


def _safe_next(request):
    target = request.POST.get("next") or request.GET.get("next") or ""
    if url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return target
    return None


@require_http_methods(["GET", "POST"])
def login_view(request):
    if request.user.is_authenticated:
        return redirect("dashboard:overview")
    if request.method == "POST":
        email = request.POST.get("email", "").strip().lower()
        blocked, key = _too_many_attempts(request, "login", email)
        user = None if blocked else authenticate(request, email=email, password=request.POST.get("password", ""))
        if blocked:
            messages.error(request, "Too many attempts. Try again in a few minutes.")
        elif user is None or not user.is_active:
            _record_failure(key)
            messages.error(request, "Invalid email or password.")
        elif user.mfa_enabled:
            request.session[MFA_SESSION_KEY] = {"uid": user.pk, "ts": time.time(), "next": _safe_next(request)}
            return redirect("dashboard:login_mfa")
        else:
            login(request, user, backend="django.contrib.auth.backends.ModelBackend")
            return redirect(_safe_next(request) or "dashboard:overview")
    return render(request, "dashboard/auth/login.html", {"next": request.GET.get("next", "")})


@require_http_methods(["GET", "POST"])
def login_mfa_view(request):
    pending = request.session.get(MFA_SESSION_KEY)
    if not pending or time.time() - pending["ts"] > settings.MFA_CHALLENGE_MAX_AGE:
        request.session.pop(MFA_SESSION_KEY, None)
        messages.error(request, "Your sign-in session expired. Please sign in again.")
        return redirect("dashboard:login")
    if request.method == "POST":
        blocked, key = _too_many_attempts(request, "mfa", str(pending["uid"]))
        user = User.objects.filter(pk=pending["uid"], is_active=True).first()
        if blocked:
            request.session.pop(MFA_SESSION_KEY, None)
            messages.error(request, "Too many attempts. Try again in a few minutes.")
            return redirect("dashboard:login")
        if user and account_services.check_mfa_code(user, request.POST.get("code", "")):
            request.session.pop(MFA_SESSION_KEY, None)
            login(request, user, backend="django.contrib.auth.backends.ModelBackend")
            return redirect(pending.get("next") or "dashboard:overview")
        _record_failure(key)
        messages.error(request, "That code is not valid.")
    return render(request, "dashboard/auth/login_mfa.html")


@require_http_methods(["GET", "POST"])
def signup_view(request):
    if request.user.is_authenticated:
        return redirect("dashboard:overview")
    values = {}
    if request.method == "POST":
        values = {k: request.POST.get(k, "") for k in ("email", "password", "full_name", "business_name")}
        serializer = SignupSerializer(data=values)
        if serializer.is_valid():
            data = serializer.validated_data
            with transaction.atomic():
                user = User.objects.create_user(
                    email=data["email"], password=data["password"], full_name=data.get("full_name", "")
                )
                business = create_business(owner=user, name=data["business_name"])
            account_services.send_verification_email(user)
            login(request, user, backend="django.contrib.auth.backends.ModelBackend")
            request.session[SESSION_KEY] = business.id
            messages.success(request, "Welcome! Check your inbox to verify your email address.")
            return redirect("dashboard:overview")
        for error in flatten_errors(serializer.errors):
            messages.error(request, error)
    values.pop("password", None)
    return render(request, "dashboard/auth/signup.html", {"values": values})


@require_POST
def logout_view(request):
    logout(request)
    return redirect("dashboard:login")


def verify_email_view(request, token):
    try:
        account_services.verify_email(token)
        messages.success(request, "Your email address is verified.")
    except account_services.AccountError as exc:
        messages.error(request, str(exc))
    return redirect("dashboard:overview" if request.user.is_authenticated else "dashboard:login")


@require_http_methods(["GET", "POST"])
def password_reset_view(request):
    if request.method == "POST":
        account_services.send_password_reset(request.POST.get("email", "").strip())
        messages.success(request, "If an account exists for that email, we've sent a reset link.")
        return redirect("dashboard:login")
    return render(request, "dashboard/auth/password_reset.html")


@require_http_methods(["GET", "POST"])
def password_reset_confirm_view(request, uidb64, token):
    user = account_services.user_for_reset(uidb64, token)
    if user is None:
        messages.error(request, "This reset link is invalid or has expired.")
        return redirect("dashboard:password_reset")
    if request.method == "POST":
        password = request.POST.get("password", "")
        try:
            password_validation.validate_password(password, user)
        except ValidationError as exc:
            for error in exc.messages:
                messages.error(request, error)
        else:
            account_services.reset_password(uidb64, token, password)
            messages.success(request, "Password updated. Please sign in.")
            return redirect("dashboard:login")
    return render(request, "dashboard/auth/password_reset_confirm.html")
