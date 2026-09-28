"""Protection against server-side request forgery for tenant-supplied URLs."""

import ipaddress
import socket
from urllib.parse import urlparse

from django.conf import settings


class UnsafeURLError(ValueError):
    pass


def assert_public_url(url):
    """Raise UnsafeURLError unless ``url`` is http(s) and resolves only to public IPs."""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise UnsafeURLError("Only absolute http(s) URLs are allowed.")
    if settings.TOOLS_ALLOW_PRIVATE_NETWORKS:
        return
    try:
        infos = socket.getaddrinfo(parsed.hostname, parsed.port or None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise UnsafeURLError(f"Could not resolve host {parsed.hostname!r}.") from exc
    for info in infos:
        address = ipaddress.ip_address(info[4][0])
        if not address.is_global:
            raise UnsafeURLError("URLs resolving to private or internal addresses are not allowed.")
