"""§148 — outbound webhook replay protection (WebhookDispatcher).

The dispatcher used to sign ONLY the body: a captured delivery could be
replayed byte-for-byte forever, and receivers had no stable id to dedupe
redeliveries on. Every delivery now carries:

    X-SalesOS-Signature   sha256=HMAC-SHA256(secret, "<timestamp>.<body>")
    X-SalesOS-Timestamp   unix seconds — covered BY the signature
    X-SalesOS-Delivery-Id the webhook_deliveries row id (dedupe key)

These tests pin the contract from the RECEIVER's side: follow the docstring
recipe in app/modules/platform/service.py and the checks must hold — the
signature verifies only over "<timestamp>.<body>", the delivery id header is
the delivery row id, an inactive endpoint is never contacted, and the SSRF
guard still wins over any configured URL.

The database half runs on the real Postgres fixtures; the HTTP half is mocked
with httpx.MockTransport, so no network is touched.
"""

from __future__ import annotations

import hashlib
import hmac

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.platform.models import WebhookDelivery, WebhookEndpoint
from app.modules.platform.service import WebhookDispatcher

SECRET = "whsec-0123456789abcdef"


@pytest.fixture
def _bypass_dns_guard(monkeypatch):
    """The happy paths point at an unresolvable test host; the SSRF guard does
    a real DNS resolution, so the receiver-side tests stub it out at the
    consumer module (the same pattern tests/test_media_pipeline.py uses).
    The SSRF test deliberately does NOT use this fixture — it exercises the
    real guard with a literal metadata IP, which is rejected before any DNS."""
    monkeypatch.setattr(
        "app.modules.platform.service.assert_public_url", lambda url: url
    )


def _sign_body_only(secret: str, body: bytes) -> str:
    """The OLD (insecure) scheme — what a replay attacker would compute."""
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _sign_with_timestamp(secret: str, timestamp: str, body: bytes) -> str:
    covered = timestamp.encode() + b"." + body
    return "sha256=" + hmac.new(secret.encode(), covered, hashlib.sha256).hexdigest()


@pytest.fixture
async def endpoint_and_delivery(db: AsyncSession, tenant_ctx):
    endpoint = WebhookEndpoint(
        tenant_id=tenant_ctx.tenant_id,
        url="https://receiver.example.test/hooks",
        secret=SECRET,
        events=["order.created"],
        is_active=True,
    )
    db.add(endpoint)
    await db.flush()
    delivery = WebhookDelivery(
        tenant_id=tenant_ctx.tenant_id,
        webhook_id=endpoint.id,
        event_name="order.created",
        payload={"event": "order.created", "data": {"order_id": "o-1"}},
        status="queued",
    )
    db.add(delivery)
    await db.flush()
    return endpoint, delivery


def _capturing_client(captured: dict) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        captured["headers"] = {k.lower(): v for k, v in request.headers.items()}
        captured["body"] = request.content
        return httpx.Response(200)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_signature_covers_the_timestamp_not_the_body_alone(
    db, tenant_ctx, endpoint_and_delivery, _bypass_dns_guard
):
    """The core §148 property: HMAC over "<timestamp>.<body>". A signature
    computed the old way (body only) must NOT verify against the recipe."""
    _, delivery = endpoint_and_delivery
    captured: dict = {}
    result = await WebhookDispatcher.deliver(
        db,
        tenant_ctx.tenant_id,
        delivery.id,
        _client=_capturing_client(captured),
    )
    assert result.status == "delivered"

    headers = captured["headers"]
    signature = headers["x-salesos-signature"]
    timestamp = headers["x-salesos-timestamp"]
    assert timestamp.isdigit(), "the timestamp header is unix seconds"

    # The recipe from the dispatcher docstring verifies the delivery...
    assert signature == _sign_with_timestamp(
        SECRET, timestamp, captured["body"]
    )
    # ...and the old body-only signature is dead — replaying a captured
    # delivery with a forged fresh timestamp breaks the HMAC.
    assert signature != _sign_body_only(SECRET, captured["body"])

    # Tampering with the timestamp (a replay with a shifted clock) breaks it.
    stale = str(int(timestamp) - 3600)
    assert signature != _sign_with_timestamp(SECRET, stale, captured["body"])


async def test_delivery_id_header_is_the_delivery_row_id(
    db, tenant_ctx, endpoint_and_delivery, _bypass_dns_guard
):
    """Receivers dedupe redeliveries on X-SalesOS-Delivery-Id: it must be the
    webhook_deliveries row id, stable across attempts."""
    _, delivery = endpoint_and_delivery
    captured: dict = {}
    await WebhookDispatcher.deliver(
        db,
        tenant_ctx.tenant_id,
        delivery.id,
        _client=_capturing_client(captured),
    )
    assert captured["headers"]["x-salesos-delivery-id"] == str(delivery.id)


async def test_inactive_endpoint_is_skipped_without_contacting_the_receiver(
    db, tenant_ctx, endpoint_and_delivery
):
    endpoint, delivery = endpoint_and_delivery
    endpoint.is_active = False
    await db.flush()

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("an inactive endpoint must not be contacted")

    result = await WebhookDispatcher.deliver(
        db,
        tenant_ctx.tenant_id,
        delivery.id,
        _client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    assert result.status == "failed"
    assert result.last_error == "endpoint missing or inactive"


async def test_ssrf_guard_marks_the_delivery_dead_before_any_request(
    db, tenant_ctx, endpoint_and_delivery
):
    """S6: the send-time URL re-validation wins over a registered URL — a
    metadata-address endpoint is never contacted and the delivery goes DEAD
    (no retry schedule can resurrect a rejected target)."""
    endpoint, delivery = endpoint_and_delivery
    endpoint.url = "http://169.254.169.254/latest/meta-data/"
    await db.flush()

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("a blocked target must not be contacted")

    result = await WebhookDispatcher.deliver(
        db,
        tenant_ctx.tenant_id,
        delivery.id,
        _client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    assert result.status == "dead"
    assert result.last_error is not None
    assert result.last_error.startswith("endpoint url rejected")


async def test_delivered_delivery_is_never_sent_twice(
    db, tenant_ctx, endpoint_and_delivery, _bypass_dns_guard
):
    """Idempotency guard: once delivered, a replayed worker event is a no-op."""
    _, delivery = endpoint_and_delivery
    await WebhookDispatcher.deliver(
        db, tenant_ctx.tenant_id, delivery.id, _client=_capturing_client({})
    )

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("a delivered delivery must not be resent")

    result = await WebhookDispatcher.deliver(
        db,
        tenant_ctx.tenant_id,
        delivery.id,
        _client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    assert result.status == "delivered"


async def test_sign_is_stable_for_the_same_inputs():
    """The signing helper is deterministic — same secret/body/timestamp, same
    signature — so a receiver can recompute it offline."""
    body = b'{"event": "order.created"}'
    first = WebhookDispatcher.sign(SECRET, body, 1_700_000_000)
    assert first == WebhookDispatcher.sign(SECRET, body, 1_700_000_000)
    assert first.startswith("sha256=")
    assert len(first) == len("sha256=") + 64
