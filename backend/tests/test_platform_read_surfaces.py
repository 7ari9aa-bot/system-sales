"""Package 2.2 — the outbox (§19) and audit-log (§66) read surfaces.

Both tables had writers everywhere and ZERO operator readers: the outbox was
counted by diagnostics and never listed, and the audit trail was written by
every DLQ decision / tenant transition / secret rotation with nothing able to
query it back — the Wave C lesson ("built, tested in isolation, never
called") twice in one package. This file pins the operator-visible half:

* the routes exist on the platform router, gated at the ROUTE with the
  already-seeded ``settings:read`` code (no new permission strings);
* a caller without it gets 403 before any handler runs (DB-free);
* tenant isolation is EXPLICIT. ``outbox_events`` is a system table with NO
  RLS backstop — tenancy lives in ``meta["tenant_id"]``, the same key the
  relay refuses to publish without, so that predicate IS the isolation and
  another tenant's event id is a 404. ``audit_logs`` additionally hides the
  platform-level NULL-tenant rows: they carry actions taken outside any
  tenant, and exposing them through a tenant endpoint is an exposure decision
  that belongs to the platform-admin plane;
* the §66 lineage fields (``source`` / ``request_id`` / ``correlation_id``)
  surface verbatim, and a row written outside a request scope renders JSON
  ``null`` — never the STRING "null";
* the paging and filter knobs are bounded: ``limit``/``offset`` are refused
  by validation, the outbox ``status`` and audit ``source`` filters are
  closed vocabularies, and a reversed audit period is a 400, not a silently
  empty page.

Route-shape and permission-gate cases are DB-free; listing real rows needs
``DATABASE_URL_APP_ADMIN`` and skips locally without it — CI runs them.
"""

from __future__ import annotations

import uuid
from contextvars import Token
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.context import (
    actor_kind_contextvar,
    correlation_id_contextvar,
    request_id_contextvar,
)
from app.main import create_app
from app.modules.identity.deps import AuthedUser, TenantContext, get_tenant_ctx
from app.modules.identity.models import Tenant
from app.modules.platform.router import router as platform_router
from tests.test_security_events_read_surface import _permission_codes

LIST_PATHS = {
    "outbox": "/api/v1/platform/outbox-events",
    "audit": "/api/v1/platform/audit-logs",
}
ROUTE_PATHS = {
    "outbox": "/platform/outbox-events",
    "outbox_detail": "/platform/outbox-events/{event_id}",
    "audit": "/platform/audit-logs",
}


# ---------------------------------------------------------------------------
# 1. DB-free: the routes exist and are gated at the route, not in the body.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "method"),
    [
        (ROUTE_PATHS["outbox"], "GET"),
        (ROUTE_PATHS["outbox_detail"], "GET"),
        (ROUTE_PATHS["audit"], "GET"),
    ],
)
def test_the_read_routes_are_registered_on_the_platform_router(path: str, method: str) -> None:
    assert any(r.path == path and method in r.methods for r in platform_router.routes), (
        f"{method} {path} is missing — a trail nobody can query is not a trail"
    )


@pytest.mark.parametrize(
    "path",
    [ROUTE_PATHS["outbox"], ROUTE_PATHS["outbox_detail"], ROUTE_PATHS["audit"]],
)
def test_the_read_routes_are_gated_by_settings_read(path: str) -> None:
    codes = _permission_codes(platform_router.routes, path, "GET")
    assert codes == {"settings:read"}, (
        "these are settings-plane operator surfaces; gate on the code every "
        "other admin-facing read already uses — no new permission strings"
    )


def _permission_only_app(permissions: set[str]):
    """The real app with ONLY the auth context swapped; a refused caller never
    reaches a handler, so nothing touches the DB."""
    app = create_app()

    async def _ctx() -> TenantContext:
        return TenantContext(
            session=None,  # never used: the call under test is refused first
            user=AuthedUser(id=uuid.uuid4(), tenant_id=None, role_code="staff"),
            tenant_id=uuid.uuid4(),
            role_code="staff",
            permission_codes=set(permissions),
        )

    app.dependency_overrides[get_tenant_ctx] = _ctx
    return app


@pytest.mark.parametrize("path", LIST_PATHS.values())
async def test_a_caller_without_settings_read_cannot_list(path: str) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=_permission_only_app({"customers:read"})),
        base_url="http://test",
    ) as client:
        refused = await client.get(path)

    assert refused.status_code == 403, refused.text


# ---------------------------------------------------------------------------
# 2. DB-backed: isolation, filters, and the wire contract over real rows.
# ---------------------------------------------------------------------------


def _client(db, tenant_id: uuid.UUID, user_id: uuid.UUID, permissions: set[str]):
    app = create_app()

    async def _ctx() -> TenantContext:
        return TenantContext(
            session=db,
            user=AuthedUser(id=user_id, tenant_id=tenant_id, role_code="owner"),
            tenant_id=tenant_id,
            role_code="owner",
            permission_codes=set(permissions),
        )

    app.dependency_overrides[get_tenant_ctx] = _ctx
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _second_tenant(db) -> Tenant:
    other = Tenant(slug=f"other-{uuid.uuid4().hex[:8]}", name="Other Tenant")
    db.add(other)
    await db.flush()
    return other


# ------------------------------------------------------------- outbox (§19) --


async def test_outbox_list_returns_only_this_tenants_events(db, tenant_ctx) -> None:
    from app.core.events.writer import add_outbox_event

    mine = await add_outbox_event(
        db,
        aggregate_type="order",
        aggregate_id=uuid.uuid4(),
        event_type="order.created",
        tenant_id=tenant_ctx.tenant_id,
        payload={"n": 1},
    )
    other_tenant = await _second_tenant(db)
    theirs = await add_outbox_event(
        db,
        aggregate_type="order",
        aggregate_id=uuid.uuid4(),
        event_type="order.created",
        tenant_id=other_tenant.id,
        payload={"n": 2},
    )

    async with _client(db, tenant_ctx.tenant_id, tenant_ctx.user.id, {"settings:read"}) as client:
        resp = await client.get(LIST_PATHS["outbox"])

    assert resp.status_code == 200, resp.text
    body = resp.json()
    ids = {item["id"] for item in body["items"]}
    assert str(mine.id) in ids
    assert str(theirs.id) not in ids, (
        "outbox_events has NO RLS backstop — the meta->>'tenant_id' predicate "
        "is the only isolation, and another tenant's event leaked"
    )
    assert {"total", "limit", "offset", "items"} <= set(body)
    # The list is a summary: the payload body is fetched per row.
    assert all("payload" not in item for item in body["items"])


async def test_outbox_status_filter_narrows_and_unknown_status_is_refused(db, tenant_ctx) -> None:
    from app.core.events.writer import add_outbox_event

    await add_outbox_event(
        db,
        aggregate_type="order",
        aggregate_id=uuid.uuid4(),
        event_type="order.created",
        tenant_id=tenant_ctx.tenant_id,
    )

    async with _client(db, tenant_ctx.tenant_id, tenant_ctx.user.id, {"settings:read"}) as client:
        ok = await client.get(LIST_PATHS["outbox"], params={"status": "pending"})
        assert ok.status_code == 200
        assert all(i["status"] == "pending" for i in ok.json()["items"])

        bad = await client.get(LIST_PATHS["outbox"], params={"status": "banana"})

    assert bad.status_code == 400
    assert bad.json()["error"]["code"] == "validation_error"
    assert "unknown outbox event status" in bad.json()["error"]["message"]


async def test_outbox_detail_carries_payload_and_hides_other_tenants(db, tenant_ctx) -> None:
    from app.core.events.writer import add_outbox_event

    mine = await add_outbox_event(
        db,
        aggregate_type="order",
        aggregate_id=uuid.uuid4(),
        event_type="order.created",
        tenant_id=tenant_ctx.tenant_id,
        payload={"order_id": "ord-1"},
    )
    other_tenant = await _second_tenant(db)
    theirs = await add_outbox_event(
        db,
        aggregate_type="order",
        aggregate_id=uuid.uuid4(),
        event_type="order.created",
        tenant_id=other_tenant.id,
        payload={"secret": "not-yours"},
    )

    async with _client(db, tenant_ctx.tenant_id, tenant_ctx.user.id, {"settings:read"}) as client:
        detail = await client.get(f"{LIST_PATHS['outbox']}/{mine.id}")
        leaked = await client.get(f"{LIST_PATHS['outbox']}/{theirs.id}")

    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["payload"]["order_id"] == "ord-1"
    assert body["meta"]["tenant_id"] == str(tenant_ctx.tenant_id)
    assert leaked.status_code == 404, (
        "another tenant's event id must answer 404 — its existence is not the caller's business"
    )
    assert "not-yours" not in leaked.text


async def test_outbox_detail_is_gated_when_the_row_is_missing(db, tenant_ctx) -> None:
    async with _client(db, tenant_ctx.tenant_id, tenant_ctx.user.id, {"customers:read"}) as client:
        refused = await client.get(f"{LIST_PATHS['outbox']}/{uuid.uuid4()}")

    assert refused.status_code == 403


@pytest.mark.parametrize("limit", [0, 201])
async def test_outbox_limit_is_bounded(db, tenant_ctx, limit: int) -> None:
    async with _client(db, tenant_ctx.tenant_id, tenant_ctx.user.id, {"settings:read"}) as client:
        resp = await client.get(LIST_PATHS["outbox"], params={"limit": limit})
    assert resp.status_code == 422, f"limit={limit} must be refused by validation"


# --------------------------------------------------------------- audit (§66) --


async def test_audit_list_returns_only_this_tenants_rows(db, tenant_ctx) -> None:
    from app.core.db import bind_tenant
    from app.modules.platform.models import AuditLog
    from app.modules.platform.service import AuditService

    mine = await AuditService.write(
        db,
        tenant_ctx.tenant_id,
        tenant_ctx.user.id,
        "order.status_changed",
        "order",
        str(uuid.uuid4()),
    )
    other_tenant = await _second_tenant(db)
    # audit_logs is FORCE RLS: seed the other tenant's row under ITS GUC,
    # then re-bind the caller's tenant for the read (the append-only INSERT
    # policy admits only the bound tenant's rows or platform NULL rows).
    await bind_tenant(db, other_tenant.id)
    theirs = await AuditService.write(
        db,
        other_tenant.id,
        None,
        "order.status_changed",
        "order",
        str(uuid.uuid4()),
    )
    # The NULL-tenant platform row must be a PURE INSERT: the ORM adds
    # `RETURNING created_at` for server-defaulted columns, and RETURNING runs
    # the row through the SELECT policy — a NULL-tenant row is invisible to a
    # non-admin session under the fd2026100409 split. Supplying created_at
    # client-side leaves the INSERT with nothing to fetch.
    platform_row = AuditLog(
        tenant_id=None,
        actor_user_id=None,
        action="platform.action",
        resource_type="platform",
        resource_id=str(uuid.uuid4()),
        source="system",
        created_at=datetime.now(UTC),
    )
    db.add(platform_row)
    await db.flush()
    await bind_tenant(db, tenant_ctx.tenant_id)

    async with _client(db, tenant_ctx.tenant_id, tenant_ctx.user.id, {"settings:read"}) as client:
        resp = await client.get(LIST_PATHS["audit"])

    assert resp.status_code == 200, resp.text
    body = resp.json()
    ids = {item["id"] for item in body["items"]}
    assert str(mine.id) in ids
    assert str(theirs.id) not in ids, "another tenant's audit rows leaked"
    assert str(platform_row.id) not in ids, (
        "NULL-tenant platform rows carry actions taken outside any tenant — "
        "exposing them here is a platform-admin-plane decision, not a default"
    )


async def test_audit_rows_carry_source_lineage_and_real_nulls(db, tenant_ctx) -> None:
    from app.modules.platform.service import AuditService

    req_token: Token = request_id_contextvar.set("req-22-read")
    cor_token: Token = correlation_id_contextvar.set("cor-22-read")
    kind_token: Token = actor_kind_contextvar.set("automation")
    try:
        scoped = await AuditService.write(
            db,
            tenant_ctx.tenant_id,
            tenant_ctx.user.id,
            "test.lineage_read",
            "customer",
            str(uuid.uuid4()),
        )
    finally:
        request_id_contextvar.reset(req_token)
        correlation_id_contextvar.reset(cor_token)
        actor_kind_contextvar.reset(kind_token)

    # Same action, written OUTSIDE the request scope: the ids are genuinely
    # NULL, which is what distinguishes a NULL from the string "null" on the
    # wire when both rows come back under the same filter.
    unscoped = await AuditService.write(
        db,
        tenant_ctx.tenant_id,
        tenant_ctx.user.id,
        "test.lineage_read",
        "customer",
        str(uuid.uuid4()),
    )

    async with _client(db, tenant_ctx.tenant_id, tenant_ctx.user.id, {"settings:read"}) as client:
        resp = await client.get(LIST_PATHS["audit"], params={"action": "test.lineage_read"})

    assert resp.status_code == 200, resp.text
    items = {item["id"]: item for item in resp.json()["items"]}
    row = items[str(scoped.id)]
    assert row["source"] == "automation"
    assert row["request_id"] == "req-22-read"
    assert row["correlation_id"] == "cor-22-read"

    bare = items[str(unscoped.id)]
    assert bare["request_id"] is None, "a NULL id must render as JSON null"
    assert bare["correlation_id"] is None
    assert bare["request_id"] != "null", "NULL must not become the STRING 'null'"
    assert bare["source"] == "human", "the §66 default when no actor kind is set"


async def test_audit_filters_narrow_the_read_and_stay_bounded(db, tenant_ctx) -> None:
    from app.modules.platform.service import AuditService

    kept = await AuditService.write(
        db,
        tenant_ctx.tenant_id,
        tenant_ctx.user.id,
        "webhook_event.ignored",
        "webhook_event",
        str(uuid.uuid4()),
    )
    await AuditService.write(
        db,
        tenant_ctx.tenant_id,
        tenant_ctx.user.id,
        "order.status_changed",
        "order",
        str(uuid.uuid4()),
    )

    async with _client(db, tenant_ctx.tenant_id, tenant_ctx.user.id, {"settings:read"}) as client:
        by_action = await client.get(
            LIST_PATHS["audit"], params={"action": "webhook_event.ignored"}
        )
        assert by_action.status_code == 200
        assert [i["action"] for i in by_action.json()["items"]] == ["webhook_event.ignored"]
        assert {i["id"] for i in by_action.json()["items"]} == {str(kept.id)}

        by_type = await client.get(LIST_PATHS["audit"], params={"resource_type": "webhook_event"})
        assert by_type.status_code == 200
        assert all(i["resource_type"] == "webhook_event" for i in by_type.json()["items"])

        bad_source = await client.get(LIST_PATHS["audit"], params={"source": "wizard"})
        assert bad_source.status_code == 400

        reversed_period = await client.get(
            LIST_PATHS["audit"],
            params={
                "since": datetime.now(UTC).isoformat(),
                "until": (datetime.now(UTC) - timedelta(days=1)).isoformat(),
            },
        )
        assert reversed_period.status_code == 400, (
            "a reversed period must be refused, not answered with a silent empty page"
        )


async def test_audit_period_filter_excludes_rows_before_since(db, tenant_ctx) -> None:
    """The period filter reads real timestamps: a row stamped before ``since``
    is excluded, a row after it is kept — the filter is a period, not a no-op."""
    from app.core.context import actor_kind_contextvar
    from app.modules.platform.models import AuditLog

    # Shape created_at at INSERT time: audit_logs is append-only at the
    # database layer (fd2026100409 — no UPDATE policy), so a timestamp can
    # only be set when the row is written.
    old = AuditLog(
        tenant_id=tenant_ctx.tenant_id,
        actor_user_id=tenant_ctx.user.id,
        action="test.period_probe_old",
        resource_type="order",
        resource_id=str(uuid.uuid4()),
        source=actor_kind_contextvar.get() or "human",
        created_at=datetime.now(UTC) - timedelta(days=2),
    )
    fresh = AuditLog(
        tenant_id=tenant_ctx.tenant_id,
        actor_user_id=tenant_ctx.user.id,
        action="test.period_probe_new",
        resource_type="order",
        resource_id=str(uuid.uuid4()),
        source=actor_kind_contextvar.get() or "human",
    )
    db.add_all([old, fresh])
    await db.flush()

    async with _client(db, tenant_ctx.tenant_id, tenant_ctx.user.id, {"settings:read"}) as client:
        resp = await client.get(
            LIST_PATHS["audit"],
            params={"since": (datetime.now(UTC) - timedelta(days=1)).isoformat()},
        )

    assert resp.status_code == 200, resp.text
    ids = {item["id"] for item in resp.json()["items"]}
    assert ids == {str(fresh.id)}, (
        "the row stamped two days ago is outside the period and must be "
        "excluded — the filter must actually bind"
    )


@pytest.mark.parametrize("limit", [0, 201])
async def test_audit_limit_is_bounded(db, tenant_ctx, limit: int) -> None:
    async with _client(db, tenant_ctx.tenant_id, tenant_ctx.user.id, {"settings:read"}) as client:
        resp = await client.get(LIST_PATHS["audit"], params={"limit": limit})
    assert resp.status_code == 422, f"limit={limit} must be refused by validation"
