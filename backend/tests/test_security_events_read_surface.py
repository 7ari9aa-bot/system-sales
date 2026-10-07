"""§67 read surface — `GET /platform/security-events` (Wave C closure).

The roadmap's own lesson (docs/ROADMAP_TO_90.md, Wave C): the failure mode is
"built, tested in isolation, and never called". `security_events` had nine
production writers and ZERO readers — no router, no CLI, nothing SELECTed the
table outside tests. A trail nobody can query is not a trail.

This file pins the operator-visible half:

* the route exists on the platform router and is gated at the ROUTE with the
  already-seeded `settings:read` code (no new permission strings);
* a caller without it gets 403 before any handler runs (DB-free);
* tenant isolation is explicit: a caller sees ONLY rows attributed to their
  own tenant — not another tenant's, and not the pre-auth NULL-tenant rows,
  whose exposure policy is a platform-admin-plane decision this endpoint
  deliberately does not make;
* §146 redaction: `details` values under PII keys are nulled unless the caller
  holds `pii:read`, and secret keys (`vault_key`, tokens) are nulled ALWAYS.

Route-shape and permission-gate cases are DB-free; listing real rows needs
`DATABASE_URL_APP_ADMIN` and skips locally — CI proves them.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.db import bind_tenant
from app.main import create_app
from app.modules.identity.deps import AuthedUser, TenantContext, get_tenant_ctx
from app.modules.identity.models import Tenant
from app.modules.platform.models import SecurityEvent
from app.modules.platform.router import router as platform_router

LIST_PATH = "/api/v1/platform/security-events"
ROUTE_PATH = "/platform/security-events"


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


# ---------------------------------------------------------------------------
# 1. DB-free: the route exists and is gated at the route, not in the body.
# ---------------------------------------------------------------------------


def test_the_security_events_route_is_registered_on_the_platform_router() -> None:
    assert any(r.path == ROUTE_PATH and "GET" in r.methods for r in platform_router.routes), (
        "security_events has writers but no reader — §67 needs its query surface"
    )


def test_listing_security_events_is_gated_by_settings_read() -> None:
    codes = _permission_codes(platform_router.routes, ROUTE_PATH, "GET")
    assert codes == {"settings:read"}, (
        "the trail is a settings-plane operator surface; gate on the code every "
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


async def test_a_caller_without_settings_read_cannot_list() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=_permission_only_app({"customers:read"})),
        base_url="http://test",
    ) as client:
        refused = await client.get(LIST_PATH)

    assert refused.status_code == 403, refused.text


# ---------------------------------------------------------------------------
# 2. DB-backed (CI): isolation + §146 redaction over real rows.
# ---------------------------------------------------------------------------


async def _seed(
    db,
    *,
    tenant_id: uuid.UUID | None,
    event_type: str,
    details: dict,
    created_at: datetime | None = None,
) -> uuid.UUID:
    """Insert one event row with the given tenant attribution.

    `security_events` is FORCE RLS with the fd2026100409 append-only split —
    INSERT only — so a tenant-scoped row needs the GUC bound, the pre-auth
    NULL row needs none, and any timestamp shaping must happen at INSERT
    time: an UPDATE would be refused by RLS by design.
    """
    if tenant_id is not None:
        await bind_tenant(db, tenant_id)
    else:
        # The ORM RETURNs server-defaulted columns, and RETURNING runs the row
        # through the SELECT policy — a NULL-tenant row is invisible to a
        # non-admin session under the fd2026100409 split. Supplying created_at
        # client-side leaves the INSERT with nothing to fetch, so the seed
        # stays a pure INSERT the *_insert policy can admit.
        if created_at is None:
            created_at = datetime.now(UTC)
    event = SecurityEvent(
        event_type=event_type,
        tenant_id=tenant_id,
        actor_user_id=None,
        details=details,
        ip="203.0.113.7",
        created_at=created_at,
    )
    db.add(event)
    await db.flush()
    return event.id


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


async def test_a_tenant_sees_only_its_own_security_events(db, tenant_ctx) -> None:
    """Explicit tenant filter + FORCE RLS: another tenant's rows and the
    pre-auth NULL-tenant rows are not this caller's trail."""
    # a real second tenant so the FK/RLS semantics are honest
    other = Tenant(slug=f"other-{uuid.uuid4().hex[:8]}", name="Other Tenant")
    db.add(other)
    await db.flush()
    other_tenant = other.id

    mine = await _seed(
        db,
        tenant_id=tenant_ctx.tenant_id,
        event_type="role_changed",
        details={"email": "someone@corp.test", "to_role": "manager"},
    )
    theirs = await _seed(
        db,
        tenant_id=other_tenant,
        event_type="role_changed",
        details={"email": "other@corp.test", "to_role": "manager"},
    )
    preauth = await _seed(
        db,
        tenant_id=None,
        event_type="login_failure",
        details={"email_domain": "corp.test"},
    )
    await bind_tenant(db, tenant_ctx.tenant_id)

    async with _client(db, tenant_ctx.tenant_id, tenant_ctx.user.id, {"settings:read"}) as client:
        resp = await client.get(LIST_PATH)

    assert resp.status_code == 200, resp.text
    ids = {item["id"] for item in resp.json()["items"]}
    assert ids == {str(mine)}, (
        f"expected exactly this tenant's event, got {ids} — other={theirs} leaks, "
        f"pre-auth={preauth} has no agreed exposure policy and must not default-open"
    )


async def test_details_are_redacted_per_146_without_pii_read(db, tenant_ctx) -> None:
    """PII keys in details are nulled unless `pii:read`; secret keys ALWAYS."""
    await _seed(
        db,
        tenant_id=tenant_ctx.tenant_id,
        event_type="api_key_created",
        details={"provider": "twilio", "email": "a@b.test", "vault_key": "secret/abc"},
    )

    async with _client(db, tenant_ctx.tenant_id, tenant_ctx.user.id, {"settings:read"}) as client:
        naked = (await client.get(LIST_PATH)).json()["items"][0]

    assert naked["details"]["email"] is None, "PII without pii:read must be nulled"
    assert naked["details"]["vault_key"] is None, "secret fields are ALWAYS nulled"
    assert naked["details"]["provider"] == "twilio", "non-sensitive keys survive"

    async with _client(
        db, tenant_ctx.tenant_id, tenant_ctx.user.id, {"settings:read", "pii:read"}
    ) as client:
        allowed = (await client.get(LIST_PATH)).json()["items"][0]
    assert allowed["details"]["email"] == "a@b.test"
    assert allowed["details"]["vault_key"] is None, (
        "pii:read opens PII — never secrets (field_auth §146: secrets leave only "
        "through SecretStorePort)"
    )


async def test_event_type_filter_narrows_the_trail(db, tenant_ctx) -> None:
    await _seed(
        db,
        tenant_id=tenant_ctx.tenant_id,
        event_type="role_changed",
        details={},
    )
    await _seed(
        db,
        tenant_id=tenant_ctx.tenant_id,
        event_type="token_reuse_detected",
        details={},
    )

    async with _client(db, tenant_ctx.tenant_id, tenant_ctx.user.id, {"settings:read"}) as client:
        resp = await client.get(LIST_PATH, params={"event_type": "role_changed"})

    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    assert [i["event_type"] for i in items] == ["role_changed"]


@pytest.mark.parametrize("limit", [0, 201])
async def test_limit_is_bounded(db, tenant_ctx, limit: int) -> None:
    """The operator surface must not be a full-table dump knob."""
    async with _client(db, tenant_ctx.tenant_id, tenant_ctx.user.id, {"settings:read"}) as client:
        resp = await client.get(LIST_PATH, params={"limit": limit})
    assert resp.status_code == 422, f"limit={limit} must be refused by validation"


async def test_list_is_newest_first(db, tenant_ctx) -> None:
    await _seed(
        db,
        tenant_id=tenant_ctx.tenant_id,
        event_type="role_changed",
        details={"n": 1},
        # distinct created_at so the order assertion is deterministic —
        # shaped at INSERT time (append-only; no UPDATE path exists)
        created_at=datetime.now(UTC) - timedelta(hours=1),
    )
    await _seed(
        db,
        tenant_id=tenant_ctx.tenant_id,
        event_type="role_changed",
        details={"n": 2},
    )

    async with _client(db, tenant_ctx.tenant_id, tenant_ctx.user.id, {"settings:read"}) as client:
        items = (await client.get(LIST_PATH)).json()["items"]

    # Two claims, pinned together:
    # 1. newest first — the row backdated an hour (n=1) sorts AFTER the fresh one (n=2);
    # 2. the wire type — `n` is a JSONB seq marker, NOT money. §47/ADR-053 send only
    #    Decimal money across JSON as a string; counts, ids and ordinary numbers stay
    #    JSON numbers, so redact_fields passes it through as an int. Asserting ints here
    #    also rejects a silent str() coercion or float() (both would be wrong contracts).
    seq = [i["details"]["n"] for i in items]
    assert seq == [2, 1], f"newest first, as numbers: {seq!r}"
    assert all(isinstance(v, int) and not isinstance(v, bool) for v in seq), (
        f"non-money numbers stay ints on the wire, got {[type(v).__name__ for v in seq]}"
    )
