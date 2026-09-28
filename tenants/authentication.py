import hmac

from django.utils import timezone
from rest_framework import authentication, exceptions

from .models import APIKey


class APIKeyPrincipal:
    """Stand-in for ``request.user`` when a request authenticates with an API key."""

    is_authenticated = True
    is_anonymous = False
    is_active = True
    is_staff = False
    is_superuser = False

    def __init__(self, api_key):
        self.api_key = api_key
        # Unique per key, so per-user throttling works for API clients too.
        self.pk = self.id = f"apikey-{api_key.pk}"
        self.email = f"api-key:{api_key.name}"

    def __str__(self):
        return self.email


class APIKeyAuthentication(authentication.BaseAuthentication):
    keyword = "Api-Key"

    def authenticate(self, request):
        header = authentication.get_authorization_header(request).decode(errors="ignore")
        if not header.startswith(f"{self.keyword} "):
            return None
        raw = header[len(self.keyword) + 1:].strip()
        parts = raw.split("_")
        if len(parts) < 3 or parts[0] != "wak":
            raise exceptions.AuthenticationFailed("Invalid API key.")
        key = APIKey.objects.select_related("business").filter(prefix=parts[1], revoked_at__isnull=True).first()
        if key is None or not hmac.compare_digest(key.key_hash, APIKey.hash(raw)):
            raise exceptions.AuthenticationFailed("Invalid API key.")
        if key.last_used_at is None or (timezone.now() - key.last_used_at).total_seconds() > 60:
            APIKey.objects.filter(pk=key.pk).update(last_used_at=timezone.now())
        return APIKeyPrincipal(key), key

    def authenticate_header(self, request):
        return self.keyword
