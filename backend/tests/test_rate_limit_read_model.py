"""Section 20's two reads: the request ceilings, and the webhook delivery log.

Both pages answer a question the product could not answer before, and both could lie in the
same way — by reporting a table that is not the one the code runs on:

* ``GET /platform/rate-limits`` reports ``RATE_LIMIT_BUCKETS``, the tuple the middleware's
  own ``_bucket_for`` maps paths onto. If someone adds a bucket to the ``if`` chain and not to
  the table, the page silently stops describing the system, so the first test here walks
  representative paths through the real classifier and checks every answer is in the table.
* ``GET /webhook-endpoints/deliveries`` reports the delivery rows — status, attempts, response
  code, error — and never the payload: the body is the customer event, and a settings screen
  is not the place to echo it back.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import bind_tenant
from app.core.middleware import RATE_LIMIT_BUCKETS, RATE_LIMIT_WINDOW_SECONDS, _bucket_for
from app.main import create_app
from app.modules.identity.deps import AuthedUser, TenantContext, get_tenant_ctx
from app.modules.platform.models import WebhookDelivery, WebhookEndpoint


def _app_for(db: AsyncSession, tenant_id: uuid.UUID, *, permissions: set[str] | None = None):
    ctx = TenantContext(
        session=db,
        user=AuthedUser(id=uuid.uuid4(), tenant_id=tenant_id, role_code="owner"),
        tenant_id=tenant_id,
        role_code="owner",
        permission_codes=permissions if permissions is not None else {"settings:read"},
    )
    app = create_app()

    async def _ctx() -> TenantContext:
        return ctx

    app.dependency_overrides[get_tenant_ctx] = _ctx
    return app


async def _get(app, path: str):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.get(path)


# ------------------------------------------------------------- the ceilings --


def test_every_path_the_classifier_can_answer_is_in_the_reported_table() -> None:
    """The read model must describe the middleware, not a copy of it that drifted."""
    known = {bucket for bucket, _ in RATE_LIMIT_BUCKETS}
    for path in (
        "/api/v1/auth/login",
        "/api/v1/auth/me",
        "/api/v1/auth/refresh",
        "/api/v1/webchat/session",
        "/api/v1/webhooks/whatsapp",
        "/api/v1/public/telemetry",
        "/api/v1/orders",
        "/healthz",
    ):
        bucket, limit = _bucket_for(path)
        assert bucket in known, f"{path} classified as {bucket}, which the table does not report"
        assert dict(RATE_LIMIT_BUCKETS)[bucket] == limit


async def test_the_rate_limit_read_reports_the_table_and_the_switch(
    db: AsyncSession, tenant_ctx
) -> None:
    response = await _get(_app_for(db, tenant_ctx.tenant_id), "/api/v1/platform/rate-limits")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["window_seconds"] == RATE_LIMIT_WINDOW_SECONDS
    assert isinstance(body["enforced"], bool)
    reported = {row["bucket"]: row["limit"] for row in body["buckets"]}
    assert reported == dict(RATE_LIMIT_BUCKETS)


async def test_a_member_without_settings_read_cannot_read_the_ceilings(
    db: AsyncSession, tenant_ctx
) -> None:
    response = await _get(
        _app_for(db, tenant_ctx.tenant_id, permissions=set()), "/api/v1/platform/rate-limits"
    )

    assert response.status_code == 403


# --------------------------------------------------------- the delivery log --


async def _endpoint(db: AsyncSession, tenant_id: uuid.UUID, url: str) -> WebhookEndpoint:
    row = WebhookEndpoint(
        tenant_id=tenant_id, url=url, secret="s3cret", events=["order.created"], is_active=True
    )
    db.add(row)
    await db.flush()
    return row


async def _delivery(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    endpoint: WebhookEndpoint,
    *,
    status: str = "delivered",
    last_error: str | None = None,
    response_code: int | None = 200,
) -> WebhookDelivery:
    row = WebhookDelivery(
        tenant_id=tenant_id,
        webhook_id=endpoint.id,
        event_name="order.created",
        payload={"event": "order.created", "data": {"customer_phone": "+201000000000"}},
        status=status,
        attempts=1,
        response_code=response_code,
        last_error=last_error,
        delivered_at=datetime.now(UTC) if status == "delivered" else None,
    )
    db.add(row)
    await db.flush()
    return row


async def test_the_delivery_log_reports_the_attempt_and_never_the_payload(
    db: AsyncSession, tenant_ctx
) -> None:
    endpoint = await _endpoint(db, tenant_ctx.tenant_id, "https://example.test/hook")
    await _delivery(
        db,
        tenant_ctx.tenant_id,
        endpoint,
        status="failed",
        response_code=500,
        last_error="connection reset",
    )

    response = await _get(
        _app_for(db, tenant_ctx.tenant_id), "/api/v1/webhook-endpoints/deliveries"
    )

    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert items, "the delivery just created must be listed"
    row = items[0]
    assert row["status"] == "failed"
    assert row["response_code"] == 500
    assert row["last_error"] == "connection reset"
    assert "payload" not in row
    assert "+201000000000" not in response.text, "customer data must not come back out"


async def test_another_tenants_delivery_is_not_listed(db: AsyncSession, tenant_ctx) -> None:
    # A REAL second tenant: ``webhooks.tenant_id`` is a foreign key, so a made-up uuid
    # cannot carry a row and the isolation check would pass by failing to insert at all.
    other = uuid.uuid4()
    await db.execute(
        text("INSERT INTO tenants (id, slug, name) VALUES (:id, :slug, 'Other tenant')"),
        {"id": str(other), "slug": f"other-{other.hex[:8]}"},
    )
    # webhooks and their deliveries are FORCE-tenant-isolated: each tenant's rows seed
    # under ITS GUC, so the other tenant's row is written while bound to the other tenant.
    await bind_tenant(db, other)
    other_endpoint = await _endpoint(db, other, "https://theirs.test/hook")
    await _delivery(db, other, other_endpoint)
    await bind_tenant(db, tenant_ctx.tenant_id)
    ours = await _endpoint(db, tenant_ctx.tenant_id, "https://ours.test/hook")
    await _delivery(db, tenant_ctx.tenant_id, ours)

    response = await _get(
        _app_for(db, tenant_ctx.tenant_id), "/api/v1/webhook-endpoints/deliveries"
    )

    urls = {row["webhook_id"] for row in response.json()["items"]}
    assert str(ours.id) in urls
    assert str(other_endpoint.id) not in urls


async def test_the_status_filter_is_validated_rather_than_ignored(
    db: AsyncSession, tenant_ctx
) -> None:
    app = _app_for(db, tenant_ctx.tenant_id)
    good = await _get(app, "/api/v1/webhook-endpoints/deliveries?status=dead")
    assert good.status_code == 200
    bad = await _get(app, "/api/v1/webhook-endpoints/deliveries?status=maybe")
    assert bad.status_code == 400
    assert bad.json()["error"]["code"] == "validation_error"


async def test_the_static_deliveries_path_resolves_to_its_own_route(
    db: AsyncSession, tenant_ctx
) -> None:
    """Pinned because the neighbouring routes take a path parameter.

    ``/deliveries`` and ``/{endpoint_id}/rotate`` differ by method today, so nothing is
    shadowed — but FastAPI matches in declaration order, and the day a
    ``GET /webhook-endpoints/{endpoint_id}`` is added, a static segment declared after it
    would be read as an id. This test fails the moment that ordering is broken.
    """
    response = await _get(
        _app_for(db, tenant_ctx.tenant_id), "/api/v1/webhook-endpoints/deliveries"
    )
    assert response.status_code == 200, "the static path must not be parsed as an id"
