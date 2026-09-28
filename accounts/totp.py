"""RFC 6238 time-based one-time passwords (authenticator apps)."""

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

STEP = 30
DIGITS = 6


def generate_secret():
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _code(secret, counter):
    key = base64.b32decode(secret + "=" * (-len(secret) % 8))
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(value % 10**DIGITS).zfill(DIGITS)


def current_code(secret, now=None):
    return _code(secret, int((now or time.time()) // STEP))


def match_counter(secret, code, window=1, now=None):
    """Return the matching time-step counter, or None. Allows +/- ``window`` steps of clock drift."""
    code = (code or "").replace(" ", "")
    if len(code) != DIGITS or not code.isdigit():
        return None
    counter = int((now or time.time()) // STEP)
    for delta in range(-window, window + 1):
        if hmac.compare_digest(_code(secret, counter + delta), code):
            return counter + delta
    return None


def provisioning_uri(secret, account, issuer):
    label = quote(f"{issuer}:{account}")
    return f"otpauth://totp/{label}?secret={secret}&issuer={quote(issuer)}&digits={DIGITS}&period={STEP}"
