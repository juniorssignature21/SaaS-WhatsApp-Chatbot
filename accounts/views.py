from django.db import transaction
from rest_framework import generics, permissions, status
from rest_framework.authtoken.models import Token
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from tenants.permissions import IsHumanUser
from tenants.serializers import BusinessSerializer
from tenants.services import create_business

from . import services
from .models import User
from .serializers import (
    EmailTokenSerializer,
    LoginSerializer,
    MFACodeSerializer,
    MFALoginSerializer,
    PasswordChangeSerializer,
    PasswordResetConfirmSerializer,
    PasswordResetRequestSerializer,
    SignupSerializer,
    UserSerializer,
)


class AuthThrottleMixin:
    permission_classes = [permissions.AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth"


def _token_response(user):
    token, _ = Token.objects.get_or_create(user=user)
    return {"token": token.key, "user": UserSerializer(user).data}


def _raise(exc):
    raise ValidationError({"detail": str(exc)}) from exc


class SignupView(AuthThrottleMixin, APIView):
    """Create a user together with their first business (they become OWNER)."""

    def post(self, request):
        serializer = SignupSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        with transaction.atomic():
            user = User.objects.create_user(
                email=data["email"], password=data["password"], full_name=data.get("full_name", "")
            )
            business = create_business(owner=user, name=data["business_name"])
        transaction.on_commit(lambda: services.send_verification_email(user))
        return Response(
            {**_token_response(user), "business": BusinessSerializer(business).data},
            status=status.HTTP_201_CREATED,
        )


class LoginView(AuthThrottleMixin, APIView):
    """Step 1. Returns a token, or ``mfa_required`` with a short-lived ``mfa_token``."""

    def post(self, request):
        serializer = LoginSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data["user"]
        if user.mfa_enabled:
            return Response({"mfa_required": True, "mfa_token": services.make_mfa_challenge(user)})
        return Response(_token_response(user))


class MFALoginView(AuthThrottleMixin, APIView):
    """Step 2 for accounts with two-factor authentication."""

    def post(self, request):
        serializer = MFALoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            user = services.resolve_mfa_challenge(serializer.validated_data["mfa_token"])
        except services.AccountError as exc:
            _raise(exc)
        if not services.check_mfa_code(user, serializer.validated_data["code"]):
            raise ValidationError({"code": "Invalid code."})
        return Response(_token_response(user))


class LogoutView(APIView):
    permission_classes = [IsHumanUser]

    def post(self, request):
        Token.objects.filter(user=request.user).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(generics.RetrieveUpdateAPIView):
    serializer_class = UserSerializer
    permission_classes = [IsHumanUser]

    def get_object(self):
        return self.request.user


class VerifyEmailView(AuthThrottleMixin, APIView):
    def post(self, request):
        serializer = EmailTokenSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            user = services.verify_email(serializer.validated_data["token"])
        except services.AccountError as exc:
            _raise(exc)
        return Response(UserSerializer(user).data)


class ResendVerificationView(APIView):
    permission_classes = [IsHumanUser]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth"

    def post(self, request):
        if not request.user.email_verified:
            services.send_verification_email(request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)


class PasswordResetRequestView(AuthThrottleMixin, APIView):
    def post(self, request):
        serializer = PasswordResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.send_password_reset(serializer.validated_data["email"])
        # Same response whether or not the account exists.
        return Response({"detail": "If the account exists, a reset link has been sent."})


class PasswordResetConfirmView(AuthThrottleMixin, APIView):
    def post(self, request):
        serializer = PasswordResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            services.reset_password(data["uid"], data["token"], data["new_password"])
        except services.AccountError as exc:
            _raise(exc)
        return Response({"detail": "Password updated. Please sign in."})


class PasswordChangeView(APIView):
    permission_classes = [IsHumanUser]

    def post(self, request):
        serializer = PasswordChangeSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        request.user.set_password(serializer.validated_data["new_password"])
        request.user.save(update_fields=["password"])
        Token.objects.filter(user=request.user).delete()
        return Response(_token_response(request.user))


class MFASetupView(APIView):
    """GET starts setup (returns secret + otpauth URI); POST confirms with a code."""

    permission_classes = [IsHumanUser]

    def get(self, request):
        try:
            secret, uri = services.begin_mfa_setup(request.user)
        except services.AccountError as exc:
            _raise(exc)
        return Response({"secret": secret, "otpauth_uri": uri})

    def post(self, request):
        serializer = MFACodeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            codes = services.enable_mfa(request.user, serializer.validated_data["code"])
        except services.AccountError as exc:
            _raise(exc)
        return Response({"recovery_codes": codes})


class MFADisableView(APIView):
    permission_classes = [IsHumanUser]

    def post(self, request):
        serializer = MFACodeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            services.disable_mfa(request.user, serializer.validated_data["code"])
        except services.AccountError as exc:
            _raise(exc)
        return Response(status=status.HTTP_204_NO_CONTENT)
