"""Account security flows: email verification, password reset and MFA."""

import hashlib
import secrets

from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.core import signing
from django.core.mail import send_mail
from django.urls import reverse
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode

from . import totp
from .models import User

EMAIL_SALT = "accounts.email-verification"
MFA_SALT = "accounts.mfa-challenge"
RECOVERY_CODE_COUNT = 8


class AccountError(Exception):
    pass


def _absolute(path):
    return f"{settings.SITE_URL}{path}"


# --- Email verification ------------------------------------------------------

def make_email_token(user):
    return signing.dumps({"uid": user.pk, "email": user.email}, salt=EMAIL_SALT)


def send_verification_email(user):
    link = _absolute(reverse("dashboard:verify_email", args=[make_email_token(user)]))
    send_mail(
        f"Verify your email for {settings.PLATFORM_NAME}",
        f"Hi {user.full_name or ''},\n\nConfirm your email address by opening this link:\n{link}\n\n"
        "The link is valid for 3 days. If you did not sign up, ignore this email.",
        settings.DEFAULT_FROM_EMAIL,
        [user.email],
    )


def verify_email(token):
    try:
        data = signing.loads(token, salt=EMAIL_SALT, max_age=settings.EMAIL_VERIFICATION_MAX_AGE)
    except signing.BadSignature as exc:
        raise AccountError("This verification link is invalid or has expired.") from exc
    user = User.objects.filter(pk=data["uid"], email=data["email"]).first()
    if user is None:
        raise AccountError("This verification link is invalid or has expired.")
    if not user.email_verified:
        user.email_verified = True
        user.save(update_fields=["email_verified"])
    return user


# --- Password reset ----------------------------------------------------------

def send_password_reset(email):
    """Email a reset link. Silent when the address is unknown (no account enumeration)."""
    user = User.objects.filter(email=email.lower(), is_active=True).first()
    if user is None:
        return
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    link = _absolute(reverse("dashboard:password_reset_confirm", args=[uid, token]))
    send_mail(
        f"Reset your {settings.PLATFORM_NAME} password",
        f"Open this link to choose a new password:\n{link}\n\nIf you did not ask for this, ignore this email.",
        settings.DEFAULT_FROM_EMAIL,
        [user.email],
    )


def user_for_reset(uidb64, token):
    try:
        user = User.objects.get(pk=force_str(urlsafe_base64_decode(uidb64)))
    except (User.DoesNotExist, ValueError, TypeError, OverflowError):
        return None
    return user if default_token_generator.check_token(user, token) else None


def reset_password(uidb64, token, new_password):
    user = user_for_reset(uidb64, token)
    if user is None:
        raise AccountError("This reset link is invalid or has expired.")
    user.set_password(new_password)
    user.save(update_fields=["password"])
    # Sign out API clients that used the old password.
    from rest_framework.authtoken.models import Token

    Token.objects.filter(user=user).delete()
    return user


# --- Two-factor authentication ----------------------------------------------

def _hash_code(code):
    return hashlib.sha256(code.replace("-", "").lower().encode()).hexdigest()


def begin_mfa_setup(user):
    """Create a new (not yet active) secret. Returns (secret, otpauth URI)."""
    if user.mfa_enabled:
        raise AccountError("Two-factor authentication is already enabled.")
    user.mfa_secret = totp.generate_secret()
    user.save(update_fields=["mfa_secret"])
    return user.mfa_secret, totp.provisioning_uri(user.mfa_secret, user.email, settings.PLATFORM_NAME)


def enable_mfa(user, code):
    """Confirm setup with a code from the app. Returns one-time recovery codes."""
    if not user.mfa_secret or user.mfa_enabled:
        raise AccountError("Start two-factor setup first.")
    counter = totp.match_counter(user.mfa_secret, code)
    if counter is None:
        raise AccountError("That code is not valid. Check your authenticator app and try again.")
    codes = [f"{secrets.token_hex(3)}-{secrets.token_hex(3)}" for _ in range(RECOVERY_CODE_COUNT)]
    user.mfa_enabled = True
    user.mfa_last_counter = counter
    user.mfa_recovery_codes = [_hash_code(c) for c in codes]
    user.save(update_fields=["mfa_enabled", "mfa_last_counter", "mfa_recovery_codes"])
    return codes


def check_mfa_code(user, code):
    """Verify an authenticator code (no replay) or consume a recovery code."""
    if not user.mfa_enabled:
        return True
    counter = totp.match_counter(user.mfa_secret, code)
    if counter is not None and (user.mfa_last_counter is None or counter > user.mfa_last_counter):
        user.mfa_last_counter = counter
        user.save(update_fields=["mfa_last_counter"])
        return True
    hashed = _hash_code(code or "")
    if hashed in user.mfa_recovery_codes:
        user.mfa_recovery_codes = [c for c in user.mfa_recovery_codes if c != hashed]
        user.save(update_fields=["mfa_recovery_codes"])
        return True
    return False


def disable_mfa(user, code):
    if not check_mfa_code(user, code):
        raise AccountError("That code is not valid.")
    user.mfa_enabled = False
    user.mfa_secret = ""
    user.mfa_last_counter = None
    user.mfa_recovery_codes = []
    user.save(update_fields=["mfa_enabled", "mfa_secret", "mfa_last_counter", "mfa_recovery_codes"])


def make_mfa_challenge(user):
    """Short-lived token proving the password step succeeded."""
    return signing.dumps({"uid": user.pk}, salt=MFA_SALT)


def resolve_mfa_challenge(token):
    try:
        data = signing.loads(token, salt=MFA_SALT, max_age=settings.MFA_CHALLENGE_MAX_AGE)
    except signing.BadSignature as exc:
        raise AccountError("Your sign-in session expired. Please sign in again.") from exc
    user = User.objects.filter(pk=data["uid"], is_active=True).first()
    if user is None:
        raise AccountError("Your sign-in session expired. Please sign in again.")
    return user
