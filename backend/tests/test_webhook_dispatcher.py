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
import uuid

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError, ValidationError
from app.modules.platform.models import WebhookDelivery, WebhookEndpoint, WebhookEvent
from app.modules.platform.router import admin_retry_webhook_event
from app.modules.platform.service import WebhookDispatcher, WebhookService

SECRET = "whsec-0123456789abcdef"


@pytest.fixture
def _bypass_dns_guard(monkeypatch):
    """The happy paths point at an unresolvable test host; the SSRF guard does
    a real DNS resolution, so the receiver-side tests stub it out at the
    consumer module (the same pattern tests/test_media_pipeline.py uses).
    The SSRF test deliberately does NOT use this fixture — it exercises the
    real guard with a literal metadata IP, which is rejected before any DNS."""
    monkeypatch.setattr("app.modules.platform.service.assert_public_url", lambda url: url)


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
    assert signature == _sign_with_timestamp(SECRET, timestamp, captured["body"])
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


# ---------------------------------------------------------------------------
# Package 2.1 — the registry surface behind the endpoints (create/rotate/
# deactivate): secret shown once, tenant-scoped, audited, SSRF-gated.
# ---------------------------------------------------------------------------


async def test_registration_rejects_internal_targets_before_any_row(db, tenant_ctx):
    """S6 at the registry: an internal/metadata URL is refused at registration
    (real net_guard, no stub) and NO endpoint row is created."""
    from sqlalchemy import func, select

    with pytest.raises(ValidationError):
        await WebhookService.register_endpoint(
            db,
            tenant_ctx.tenant_id,
            url="http://169.254.169.254/latest/meta-data/",
            events=["order.created"],
        )
    stored = (
        await db.execute(
            select(func.count(WebhookEndpoint.id)).where(
                WebhookEndpoint.tenant_id == tenant_ctx.tenant_id
            )
        )
    ).scalar_one()
    assert stored == 0


async def test_registration_issues_a_secret_once_and_audits(db, tenant_ctx, _bypass_dns_guard):
    from sqlalchemy import select

    from app.modules.platform.models import AuditLog

    endpoint = await WebhookService.register_endpoint(
        db,
        tenant_ctx.tenant_id,
        url="https://receiver.example.test/hooks",
        events=["order.created"],
        actor_user_id=tenant_ctx.user.id,
    )

    assert len(endpoint.secret) == 64  # two uuid4 hexes, server-minted
    audits = (
        (
            await db.execute(
                select(AuditLog).where(
                    AuditLog.action == "webhook_endpoint.registered",
                    AuditLog.resource_id == str(endpoint.id),
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(audits) == 1
    assert audits[0].actor_user_id == tenant_ctx.user.id
    # The audit trail records target + filter, never the secret.
    assert endpoint.secret not in str(audits[0].after)


async def test_rotation_replaces_the_secret_exactly_once_and_audits(
    db, tenant_ctx, _bypass_dns_guard
):
    """Rotate returns a NEW secret on the row (the router surfaces it once);
    the old secret is gone in the same flush, and the audit row records the
    rotation without ever carrying the new secret."""
    from sqlalchemy import select

    from app.modules.platform.models import AuditLog

    endpoint = await WebhookService.register_endpoint(
        db,
        tenant_ctx.tenant_id,
        url="https://receiver.example.test/hooks",
        events=["order.created"],
    )
    old_secret = endpoint.secret

    rotated = await WebhookService.rotate_endpoint_secret(
        db, tenant_ctx.tenant_id, endpoint.id, actor_user_id=tenant_ctx.user.id
    )

    assert rotated.id == endpoint.id
    assert rotated.secret != old_secret
    assert len(rotated.secret) == 64
    audits = (
        (
            await db.execute(
                select(AuditLog).where(
                    AuditLog.action == "webhook_endpoint.secret_rotated",
                    AuditLog.resource_id == str(endpoint.id),
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(audits) == 1
    assert old_secret not in str(audits[0].after)
    assert rotated.secret not in str(audits[0].after)


async def test_rotation_and_deactivation_are_tenant_scoped(db, tenant_ctx, _bypass_dns_guard):
    """Another tenant's endpoint id answers 404 — its very existence is not
    the caller's business — and cannot be rotated or deactivated."""
    endpoint = await WebhookService.register_endpoint(
        db,
        tenant_ctx.tenant_id,
        url="https://receiver.example.test/hooks",
        events=[],
    )
    stranger_tenant = uuid.uuid4()

    with pytest.raises(NotFoundError):
        await WebhookService.rotate_endpoint_secret(db, stranger_tenant, endpoint.id)
    with pytest.raises(NotFoundError):
        await WebhookService.deactivate_endpoint(db, stranger_tenant, endpoint.id)
    # The row is untouched by the refused stranger calls.
    assert endpoint.is_active is True


async def test_deactivation_is_soft_idempotent_and_audited_once(db, tenant_ctx, _bypass_dns_guard):
    from sqlalchemy import func, select

    from app.modules.platform.models import AuditLog

    endpoint = await WebhookService.register_endpoint(
        db,
        tenant_ctx.tenant_id,
        url="https://receiver.example.test/hooks",
        events=[],
    )

    await WebhookService.deactivate_endpoint(
        db, tenant_ctx.tenant_id, endpoint.id, actor_user_id=tenant_ctx.user.id
    )
    # Repeat DELETE is idempotent: no second audit row, no error.
    await WebhookService.deactivate_endpoint(
        db, tenant_ctx.tenant_id, endpoint.id, actor_user_id=tenant_ctx.user.id
    )

    assert endpoint.is_active is False
    assert endpoint.secret  # the row stays — the delivery history keeps its FK
    audits = (
        await db.execute(
            select(func.count(AuditLog.id)).where(
                AuditLog.action == "webhook_endpoint.deactivated",
                AuditLog.resource_id == str(endpoint.id),
            )
        )
    ).scalar_one()
    assert audits == 1


async def test_the_admin_retry_never_replays_an_unverified_row(db, tenant_ctx):
    """Fail-closed on the relay: the replay path re-runs ingest WITHOUT a fresh
    signature check, so a row that was never proven provider-signed (the flag
    the ingress router stamps) must be refused by the platform-admin surface
    instead of being turned back into messages."""
    row = WebhookEvent(
        provider="whatsapp",
        external_event_id=f"evt-{uuid.uuid4().hex[:16]}",
        tenant_id=tenant_ctx.tenant_id,
        signature_valid=False,
        payload={"signed": "nowhere"},
        processing_status="failed",
        attempts=1,
    )
    db.add(row)
    await db.flush()

    from tests.test_webhook_retry import _admin_ctx

    with pytest.raises(ValidationError, match="signature"):
        await admin_retry_webhook_event(_admin_ctx(tenant_ctx), row.id)


def _permission_codes(routes, path: str, method: str) -> set[str]:
    """RBAC codes a route declares, found by walking its dependency tree."""
    for route in routes:
        if route.path == path and method in route.methods:
            codes: set[str] = set()
            stack = list(route.dependant.dependencies)
            while stack:
                dependant = stack.pop()
                code = getattr(dependant.call, "code", None)
                if code:
                    codes.add(code)
                stack.extend(dependant.dependencies)
            return codes
    raise AssertionError(f"{method} {path} is not routed")


def test_the_registry_routes_stay_permission_gated():
    """Every registry mutation is a settings:write act (an unguarded endpoint
    registry is a credential surface), and the only read is a settings:read
    that can never see a secret."""
    from app.modules.billing.router import webhooks_router

    assert _permission_codes(webhooks_router.routes, "/webhook-endpoints", "POST") == {
        "settings:write"
    }
    assert _permission_codes(webhooks_router.routes, "/webhook-endpoints", "GET") == {
        "settings:read"
    }
    assert _permission_codes(
        webhooks_router.routes, "/webhook-endpoints/{endpoint_id}/rotate", "POST"
    ) == {"settings:write"}
    assert _permission_codes(
        webhooks_router.routes, "/webhook-endpoints/{endpoint_id}", "DELETE"
    ) == {"settings:write"}


def test_no_registry_read_response_declares_a_secret():
    """The show-once contract at the schema level: only the create/rotate
    models carry a ``secret`` field — the list/deleted models must not, so no
    read can ever be widened into a secret dump."""
    from app.modules.billing import router as billing_router_module
    from app.modules.billing.router import WebhookEndpointCreated, WebhookEndpointOut

    assert "secret" in WebhookEndpointCreated.model_fields
    assert "secret" not in WebhookEndpointOut.model_fields
    assert "secret" in billing_router_module.WebhookEndpointRotated.model_fields
    assert "secret" not in billing_router_module.WebhookEndpointDeleted.model_fields
