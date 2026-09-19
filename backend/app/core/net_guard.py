"""SSRF guard for outbound HTTP targets (S6).

Every outbound URL in this system is attacker-influenced: tenants supply the
URLs we POST webhooks to, and channel payloads supply the media URLs we fetch.
Without a guard the API becomes an open proxy — a tenant can point us at
``http://169.254.169.254/...`` (cloud instance metadata), ``http://localhost``
(our own API, bypassing the edge), or any RFC1918 host, and read the response
through error messages.

:func:`assert_public_url` rejects anything that is not a plain http(s) URL
whose host resolves entirely to public addresses.

Residual risk: DNS rebinding between this check and the real connection
(TOCTOU). Callers therefore validate at BOTH registration and send time — the
window shrinks to one resolution, which is the standard mitigation without
pinning the socket to a pre-resolved IP.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit

from app.core.errors import ValidationError

ALLOWED_SCHEMES = frozenset({"http", "https"})

# Hostnames that never need DNS to be known-bad.
BLOCKED_HOSTNAMES = frozenset(
    {
        "localhost",
        "localhost.localdomain",
        "metadata",
        "metadata.google.internal",
        "instance-data",
    }
)


def _parse_ip(raw: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    """Return the address, or None when raw is a hostname (not a literal IP)."""
    try:
        return ipaddress.ip_address(raw)
    except ValueError:
        return None


def _is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """True for anything that is not a globally routable public address."""
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def _resolve(host: str) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise ValidationError("url host did not resolve") from exc
    return sorted({str(info[4][0]) for info in infos})


def assert_public_url(url: str) -> str:
    """Validate an outbound URL and return it unchanged when it is safe.

    Raises :class:`ValidationError` (HTTP 400) for anything unsafe — never a
    500 — so a malicious tenant URL cannot be distinguished from a malformed
    one by status code.
    """
    if not url or not isinstance(url, str):
        raise ValidationError("url is required")

    parts = urlsplit(url.strip())
    if parts.scheme.lower() not in ALLOWED_SCHEMES:
        raise ValidationError("url must use http or https")
    if parts.username or parts.password:
        # user:pass@host is a classic parser-confusion vector.
        raise ValidationError("url must not embed credentials")

    host = parts.hostname
    if not host:
        raise ValidationError("url has no host")
    host = host.lower()
    if host in BLOCKED_HOSTNAMES or host.endswith(".localhost"):
        raise ValidationError("url host is not allowed")

    literal = _parse_ip(host)
    if literal is not None:
        if _is_blocked_ip(literal):
            raise ValidationError("url host is not allowed")
        return url

    for address in _resolve(host):
        parsed = _parse_ip(address)
        # An address we cannot parse is treated as unsafe (fail closed).
        if parsed is None or _is_blocked_ip(parsed):
            raise ValidationError("url resolves to a non-public address")
    return url


__all__ = ["ALLOWED_SCHEMES", "BLOCKED_HOSTNAMES", "assert_public_url"]
