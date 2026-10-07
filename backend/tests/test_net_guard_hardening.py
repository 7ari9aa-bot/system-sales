"""SSRF guard hardening pins for the DNS-resolution branch (WP 10.2, item 5).

test_security_hardening.py covers the literal-IP and scheme/credential halves
offline. What it cannot see without a network is the branch every real webhook
URL takes: the host is a NAME, so the verdict comes from ``_resolve()``. The
resolutions are monkeypatched here — the production path (parse → literal
check → resolve → per-address verdict) runs for real, only the DNS reply is
pinned. The contract is fail CLOSED: one private or unparseable address among
public ones rejects the whole URL, because a mixed record is exactly how a
rebinding attacker answers the first lookup.
"""

from __future__ import annotations

import socket

import pytest

from app.core import net_guard
from app.core.errors import ValidationError
from app.core.net_guard import assert_public_url


def _resolved_to(monkeypatch, addresses: list[str]) -> None:
    monkeypatch.setattr(net_guard, "_resolve", lambda host: addresses)


def test_a_hostname_resolving_to_a_private_address_is_rejected(monkeypatch) -> None:
    """Fail-first: this is the branch a real webhook URL always takes. If the
    per-address verdict is dropped (e.g. only the literal path checked), a
    tenant-supplied DNS name pointing into the VPC / link-local range becomes
    an open proxy to the metadata service."""
    _resolved_to(monkeypatch, ["10.0.0.5"])
    with pytest.raises(ValidationError):
        assert_public_url("https://hooks.example.test/target")


def test_a_record_mixing_public_and_private_is_rejected(monkeypatch) -> None:
    """Fail-first: one private answer among public ones must poison the whole
    verdict — that mixed record is the classic rebinding setup, and a
    first-public-wins implementation hands the attacker the second round."""
    _resolved_to(monkeypatch, ["203.0.113.7", "10.0.0.5"])
    with pytest.raises(ValidationError):
        assert_public_url("https://hooks.example.test/target")


def test_an_unparseable_resolved_address_is_rejected(monkeypatch) -> None:
    """Fail-first: a resolver answer the validator cannot parse must reject,
    never default to allow — net_guard._resolve is documented to fail closed
    on exactly this."""
    _resolved_to(monkeypatch, ["not-an-ip"])
    with pytest.raises(ValidationError):
        assert_public_url("https://hooks.example.test/target")


def test_an_all_public_resolution_is_allowed(monkeypatch) -> None:
    # 1.1.1.1 / 8.8.8.8 are genuinely global; the RFC 5737 documentation
    # ranges count as private to the ipaddress module.
    _resolved_to(monkeypatch, ["1.1.1.1", "8.8.8.8"])
    url = "https://hooks.example.test/target"
    assert assert_public_url(url) == url


def test_dns_failure_is_a_validation_error(monkeypatch) -> None:
    """Fail-first: a dead resolver must surface as the 400-shape
    ValidationError, not a raw socket error (500) — a malicious URL may not be
    distinguishable from a malformed one by status code."""

    def _boom(*args, **kwargs):  # noqa: ANN002, ANN003
        raise socket.gaierror(11001, "name resolution failed")

    monkeypatch.setattr(socket, "getaddrinfo", _boom)
    with pytest.raises(ValidationError):
        assert_public_url("https://hooks.example.test/target")


def test_an_ipv4_mapped_ipv6_literal_is_rejected() -> None:
    """Fail-first: ::ffff:10.0.0.1 is RFC1918 in a six-teen coat; a guard that
    only inspects IPv4 literals waves it straight into the private network."""
    with pytest.raises(ValidationError):
        assert_public_url("http://[::ffff:10.0.0.1]/hook")


def test_a_dotted_localhost_suffix_is_rejected() -> None:
    """Fail-first: endswith('.localhost') exists because subdomains of
    localhost resolve to the loopback without ever being the exact token —
    dropping the suffix check reopens the self-URL bypass."""
    with pytest.raises(ValidationError):
        assert_public_url("http://api.localhost/hook")


def test_scheme_is_case_insensitive_and_surrounding_whitespace_is_stripped() -> None:
    """The accept path must stay permissive on shape, strict on address: an
    uppercase scheme or a padded URL is still a plain public-IP webhook. The
    contract returns the URL UNCHANGED — stripping is the caller's job."""
    padded = "  HTTPS://1.1.1.1/hook "
    assert assert_public_url(padded) == padded
