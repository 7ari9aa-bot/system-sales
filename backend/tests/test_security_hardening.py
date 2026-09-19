"""Security hardening regression tests (S2, S3, S5, S6, S10, S12, S13).

Pure unit tests — no database, no network. Each test encodes the specific
attack it prevents, so deleting the guard fails the test rather than silently
reopening the hole.

Findings are numbered per docs/GAP_REGISTER.md.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.core.errors import ValidationError
from app.core.middleware import (
    MAX_BODY_BYTES,
    BodySizeLimitMiddleware,
    SecurityHeadersMiddleware,
)
from app.core.net_guard import assert_public_url
from app.core.security import (
    create_access_token,
    create_visitor_token,
    decode_visitor_token,
)
from app.modules.conversations.gateway.base import InboundMessage
from app.modules.conversations.gateway.ingest import IngestService
from app.modules.conversations.gateway.webchat import webchat_adapter

# --- S6: SSRF guard ----------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/latest/meta-data/",  # cloud instance metadata
        "http://127.0.0.1:8000/api/v1/auth/me",  # our own API via loopback
        "http://localhost/admin",
        "http://[::1]/",
        "http://10.0.0.5/hook",  # RFC1918
        "http://192.168.1.10/hook",
        "http://172.16.0.9/hook",
        "http://0.0.0.0/",
        "file:///etc/passwd",  # non-http scheme
        "gopher://evil.test/",
        "http://user:pass@example.com/hook",  # credentials in URL
        "http://metadata.google.internal/computeMetadata/v1/",
    ],
)
def test_ssrf_guard_rejects_internal_targets(url: str) -> None:
    with pytest.raises(ValidationError):
        assert_public_url(url)


def test_ssrf_guard_allows_public_ip_literal() -> None:
    """A literal public address needs no DNS, so this stays offline."""
    assert assert_public_url("https://1.1.1.1/hook") == "https://1.1.1.1/hook"


def test_ssrf_guard_rejects_empty() -> None:
    with pytest.raises(ValidationError):
        assert_public_url("")


# --- S5: request body size limit --------------------------------------------

_CONTENT_LENGTH_TOO_BIG = [(b"content-length", b"999999999")]


def _echo_body_app():
    """Minimal ASGI app that reads the whole body and reports its length."""

    async def app(scope, receive, send) -> None:
        total = 0
        while True:
            message = await receive()
            if message["type"] == "http.request":
                total += len(message.get("body", b""))
                if not message.get("more_body"):
                    break
            elif message["type"] == "http.disconnect":
                break
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await send({"type": "http.response.body", "body": b'{"len":%d}' % total})

    return app


def _recorder() -> tuple[list[dict[str, Any]], Any]:
    sent: list[dict[str, Any]] = []

    async def send(message) -> None:
        sent.append(message)

    return sent, send


def _status(sent: list[dict[str, Any]]) -> int | None:
    for message in sent:
        if message["type"] == "http.response.start":
            return message["status"]
    return None


async def test_body_limit_rejects_declared_oversize_before_reading() -> None:
    """A declared Content-Length over the cap is refused without buffering."""
    sent, send = _recorder()
    read = False

    async def receive():
        nonlocal read
        read = True
        return {"type": "http.request", "body": b"", "more_body": False}

    mw = BodySizeLimitMiddleware(_echo_body_app(), max_bytes=100)
    await mw(
        {"type": "http", "method": "POST", "path": "/api/v1/x", "headers": _CONTENT_LENGTH_TOO_BIG},
        receive,
        send,
    )
    assert _status(sent) == 413
    assert read is False, "body must not be read once the cap is known to be exceeded"


async def test_body_limit_rejects_streamed_oversize_without_content_length() -> None:
    """Chunked uploads declare no length — the streaming guard must catch them."""
    sent, send = _recorder()
    chunks = [b"x" * 60, b"x" * 60]

    async def receive():
        if chunks:
            return {
                "type": "http.request",
                "body": chunks.pop(0),
                "more_body": bool(chunks),
            }
        return {"type": "http.request", "body": b"", "more_body": False}

    mw = BodySizeLimitMiddleware(_echo_body_app(), max_bytes=100)
    await mw({"type": "http", "method": "POST", "path": "/x", "headers": []}, receive, send)
    assert _status(sent) == 413


async def test_body_limit_allows_small_body() -> None:
    sent, send = _recorder()

    async def receive():
        return {"type": "http.request", "body": b"x" * 10, "more_body": False}

    mw = BodySizeLimitMiddleware(_echo_body_app(), max_bytes=100)
    await mw(
        {
            "type": "http",
            "method": "POST",
            "path": "/x",
            "headers": [(b"content-length", b"10")],
        },
        receive,
        send,
    )
    assert _status(sent) == 200


def test_body_limit_default_is_one_mib() -> None:
    assert MAX_BODY_BYTES == 1_048_576


# --- S13: security headers ---------------------------------------------------


async def _run_with_headers(**kwargs) -> dict[str, str]:
    sent, send = _recorder()

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    mw = SecurityHeadersMiddleware(_echo_body_app(), **kwargs)
    await mw({"type": "http", "method": "GET", "path": "/x", "headers": []}, receive, send)
    start = next(m for m in sent if m["type"] == "http.response.start")
    return {k.decode().lower(): v.decode() for k, v in start["headers"]}


async def test_security_headers_present() -> None:
    headers = await _run_with_headers(hsts=False)
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["x-frame-options"] == "DENY"
    assert headers["referrer-policy"] == "no-referrer"
    assert "default-src 'none'" in headers["content-security-policy"]


async def test_hsts_only_when_enabled() -> None:
    """Advertising HSTS from a plaintext dev origin would poison the browser."""
    assert "strict-transport-security" not in await _run_with_headers(hsts=False)
    assert "strict-transport-security" in await _run_with_headers(hsts=True)


# --- S2: webchat visitor identity -------------------------------------------


def test_visitor_token_roundtrip() -> None:
    tenant_id = uuid.uuid4()
    token = create_visitor_token("sess-abc", str(tenant_id), widget="pk_widget")
    claims = decode_visitor_token(token)
    assert claims["sub"] == "sess-abc"
    assert claims["tenant_id"] == str(tenant_id)
    assert claims["widget"] == "pk_widget"


def test_visitor_token_rejects_staff_access_token() -> None:
    """An access token must never be usable as a visitor session."""
    access = create_access_token(str(uuid.uuid4()), {"tenant_id": str(uuid.uuid4())})
    with pytest.raises(ValidationError):
        decode_visitor_token(access)


def test_visitor_token_rejects_tampering() -> None:
    token = create_visitor_token("sess-abc", str(uuid.uuid4()), widget="pk")
    with pytest.raises(ValidationError):
        decode_visitor_token(token[:-6] + "AAAAAA")


def test_webchat_signature_check_fails_closed() -> None:
    """Webchat has no provider signature — it must never pass the generic
    webhook dispatcher, which is what allowed unauthenticated injection."""
    assert webchat_adapter.check_signature({}, b"{}") is False


# --- S3: tenant-scoped idempotency key --------------------------------------


async def test_ingest_dedupe_scope_includes_tenant(monkeypatch) -> None:
    """A channel-wide scope let an attacker pre-register another tenant's
    client_message_id; first writer wins, so the victim's message was dropped."""
    captured: dict[str, str] = {}

    async def fake_already_processed(session, scope, key):
        captured["scope"] = scope
        captured["key"] = key
        return True  # short-circuit: no DB work needed

    monkeypatch.setattr(
        IngestService, "already_processed", staticmethod(fake_already_processed)
    )
    tenant_id = uuid.uuid4()
    message = InboundMessage(
        channel="webchat",
        channel_message_id="client-msg-1",
        customer_ref="visitor-1",
        body="hello",
    )

    result = await IngestService.ingest(
        None,
        tenant_id=tenant_id,
        message=message,
        idempotency_scope="webhook:webchat",
    )

    assert result is None
    assert captured["scope"] == f"webhook:webchat:{tenant_id}"
    assert captured["key"] == "client-msg-1"
