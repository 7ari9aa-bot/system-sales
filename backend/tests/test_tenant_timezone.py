"""§47's twin for the calendar: a tenant gets its own DAY (gap §47/M10 remainder).

analytics buckets on the MERCHANT's calendar day, but until now the zone came
from ONE deployment-wide ``ANALYTICS_TIMEZONE`` (UTC fallback) because
``tenants`` had no timezone column — so a Cairo shop and a Dubai shop shared one
"day". §47 solved the identical problem for money: the currency moved from a
Python literal onto the tenant's own row, validated at the write boundary,
audited, and READ back by every surface that renders it. This does the same for
the day.

What is pinned here (all DB-free unless the section says otherwise)
------------------------------------------------------------------
1. The resolution ORDER: an explicit ``?timezone=`` from the caller wins, then
   the tenant's column, then ``ANALYTICS_TIMEZONE``, then UTC — and the answer
   says WHICH layer produced it (``source``).
2. The layering survives a caller that resolved the chain BEFORE it knew the
   tenant column existed (``analytics/router.py`` does exactly that today): a
   zone that came from a LOWER layer must not mask the tenant's own zone, while
   a zone the caller actually chose must still win.
3. Every reader that reports ``timezone`` also reports ``timezone_source``, and
   the daily buckets are computed in the same zone that is reported.
4. The write boundary refuses an unresolvable zone instead of storing it — same
   4xx class as an unknown currency code — and the change is audited.
5. The schema: a NEW nullable column descending from the previous head, with
   exactly ONE head afterwards, and no backfill (an existing row stays NULL so
   its behaviour is unchanged: the deployment zone).

The seeded two-tenant case (a Cairo shop vs. a shop with no column) needs a
real database: it skips locally when ``DATABASE_URL_APP_ADMIN`` is unset and
runs in CI. The resolution order it proves is ALSO pinned DB-free above, so a
skip never leaves the rule untested.
"""

from __future__ import annotations

import ast
import pathlib
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationError
from app.main import create_app
from app.modules.analytics import router as analytics_router
from app.modules.analytics import service as analytics_service
from app.modules.analytics.timekit import (
    FALLBACK_TIMEZONE,
    REPORTING_TZ_ENV,
    UnknownTimezoneError,
    resolve_timezone,
)
from app.modules.identity import service as identity_service
from app.modules.identity.deps import AuthedUser, TenantContext, get_tenant_ctx
from app.modules.identity.models import Tenant
from app.modules.identity.router import tenants_router
from app.modules.identity.service import TenantSettingsService
from tests.test_analytics_correctness import W1_SINCE, W1_UNTIL, _collected

TENANT = uuid.UUID("22222222-2222-2222-2222-222222222222")
#: The deployment zone these cases pretend to run under: neither Cairo nor UTC,
#: so a response naming it cannot be confused with either other layer.
DEPLOYMENT = "America/New_York"
TIMEZONE_PATH = "/tenants/{tenant_id}/timezone"

VERSIONS_DIR = pathlib.Path(__file__).resolve().parent.parent / "migrations" / "versions"
PREVIOUS_HEAD = "d5a1c7e94b02"


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


def _zone_migration() -> str:
    """The source of the migration that adds ``tenants.timezone``.

    Matched on the constraint name, not on `sa.Column("timezone"`: the schema
    already carries columns by that name (``notification_preferences.timezone``)
    and a substring cannot tell the table they belong to.
    """
    matches = [
        p
        for p in sorted(VERSIONS_DIR.glob("*.py"))
        if "tenants_timezone_shape" in p.read_text(encoding="utf-8")
    ]
    assert len(matches) == 1, f"expected one migration adding the column, got {matches}"
    return matches[0].read_text(encoding="utf-8")


class _StubResult:
    def __init__(self, row: tuple) -> None:
        self._row = row

    def first(self) -> tuple:
        return self._row


class _StubSession:
    """A session that answers ONLY the tenant's zone lookup.

    Enough to drive the resolution wiring with no database: the lookup is the
    new input, and everything above it is the chain under test.
    """

    def __init__(self, zone: str | None) -> None:
        self.zone = zone
        self.lookups = 0

    async def execute(self, statement, _params=None):  # noqa: ANN001
        sql = str(statement)
        assert "tenants" in sql, f"not the tenant-zone lookup: {sql[:60]}"
        self.lookups += 1
        return _StubResult((self.zone,))


# ================================================= the order, in one place ==


def test_the_resolution_order_is_caller_then_tenant_then_deployment_then_utc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(REPORTING_TZ_ENV, DEPLOYMENT)

    resolved = resolve_timezone("Europe/Paris", tenant_timezone="Africa/Cairo")
    assert resolved == "Europe/Paris"
    assert resolved.source == "param"

    resolved = resolve_timezone(None, tenant_timezone="Africa/Cairo")
    assert resolved == "Africa/Cairo"
    assert resolved.source == "tenant"

    resolved = resolve_timezone(None, tenant_timezone=None)
    assert resolved == DEPLOYMENT
    assert resolved.source == "deployment"

    monkeypatch.delenv(REPORTING_TZ_ENV, raising=False)
    resolved = resolve_timezone(None, tenant_timezone=None)
    assert resolved == FALLBACK_TIMEZONE
    assert resolved.source == "fallback"


def test_the_zone_still_answers_like_a_plain_string() -> None:
    """Callers that only ever wanted the name must not have to unwrap anything:
    ``ZoneInfo(zone)``, SQL binds and JSON all take it as it is."""
    resolved = resolve_timezone("Africa/Cairo")
    assert isinstance(resolved, str)
    assert resolved == "Africa/Cairo"
    assert f"{resolved}" == "Africa/Cairo"


@pytest.mark.parametrize(
    "candidate",
    ["Mars/Olympus_Mons", "Africa/Nowhere", "Africa/Cairo/Extra", "not a zone"],
)
def test_the_chain_fails_closed_on_a_zone_the_runtime_cannot_resolve(
    candidate: str,
) -> None:
    """Including a zone that is stored but no longer resolvable: silently
    bucketing such a tenant in UTC is the bug this module exists to fix."""
    with pytest.raises(UnknownTimezoneError):
        resolve_timezone(candidate)
    with pytest.raises(UnknownTimezoneError):
        resolve_timezone(None, tenant_timezone=candidate)


# ==================== the order survives a caller that resolved it first ====
#
# analytics/router.py calls resolve_timezone() on the raw query parameter and
# hands the RESULT down. A plain string cannot say whether the caller chose it
# or the deployment supplied it, and treating it as "the caller chose it" would
# let ANALYTICS_TIMEZONE mask the tenant's own column — which is the whole
# feature. The provenance therefore travels with the value.


def test_a_forwarded_deployment_zone_does_not_mask_the_tenants_column(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(REPORTING_TZ_ENV, DEPLOYMENT)
    forwarded = resolve_timezone(None)  # exactly what the router passes today

    assert forwarded == DEPLOYMENT
    assert forwarded.source == "deployment"
    assert resolve_timezone(forwarded, tenant_timezone="Africa/Cairo") == "Africa/Cairo"


def test_a_forwarded_caller_zone_still_beats_the_tenants_column(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(REPORTING_TZ_ENV, DEPLOYMENT)
    forwarded = resolve_timezone("Europe/Paris")

    assert forwarded.source == "param"
    assert resolve_timezone(forwarded, tenant_timezone="Africa/Cairo") == "Europe/Paris"


# ================================= the readers: the tenant's zone, named ====


async def test_a_reader_asks_the_tenants_row_for_its_zone() -> None:
    session = _StubSession("Africa/Cairo")
    zone = await analytics_service.resolve_report_timezone(session, TENANT)

    assert zone == "Africa/Cairo"
    assert zone.source == "tenant"
    assert session.lookups == 1


async def test_a_tenant_with_no_column_keeps_the_deployment_behaviour(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Backfilled NULLs are not a bug: an existing tenant's days must not move
    out from under it the day this ships."""
    monkeypatch.setenv(REPORTING_TZ_ENV, DEPLOYMENT)
    zone = await analytics_service.resolve_report_timezone(_StubSession(None), TENANT)

    assert zone == DEPLOYMENT
    assert zone.source == "deployment"


async def test_a_caller_zone_still_wins_over_the_column_for_one_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(REPORTING_TZ_ENV, DEPLOYMENT)
    zone = await analytics_service.resolve_report_timezone(
        _StubSession("Africa/Cairo"), TENANT, "Europe/Paris"
    )

    assert zone == "Europe/Paris"
    assert zone.source == "param"


async def test_a_stored_zone_the_runtime_cannot_resolve_fails_closed() -> None:
    """The column is validated on write, but tzdata moves; a reader must refuse
    rather than fall back to a zone the merchant never chose."""
    with pytest.raises(UnknownTimezoneError):
        await analytics_service.resolve_report_timezone(
            _StubSession("Mars/Olympus_Mons"), TENANT
        )


async def test_the_summary_reports_the_zone_and_which_layer_answered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``timezone`` alone is not honest: a reader has to be able to tell the
    merchant's own zone apart from the deployment's guess."""

    async def _money(session, tenant_id, *, since, until):
        return Decimal("0.00")

    async def _count(session, tenant_id, *, since, until):
        return 0

    async def _currency(session, tenant_id):
        return "EGP"

    monkeypatch.setattr(analytics_service, "revenue", _money)
    monkeypatch.setattr(analytics_service, "refunded_amount", _money)
    monkeypatch.setattr(analytics_service, "orders_count", _count)
    monkeypatch.setattr(analytics_service, "resolve_tenant_currency", _currency)

    summary = await analytics_service.revenue_summary(
        _StubSession("Africa/Cairo"),
        TENANT,
        since=W1_SINCE,
        until=W1_UNTIL,
    )

    assert summary["timezone"] == "Africa/Cairo"
    assert summary["timezone_source"] == "tenant"


async def test_every_daily_bucket_uses_the_same_zone_the_summary_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The SQL expresses the merchant-day rule with ``AT TIME ZONE``; a series
    bucketed on one zone and labelled with another is the M10 bug returning."""
    seen: list[str] = []

    async def _sum(session, sql, params):
        seen.append(params["tz"])
        return {}

    async def _count(session, sql, params):
        seen.append(params["tz"])
        return {}

    monkeypatch.setattr(analytics_service, "_sum_by_bucket", _sum)
    monkeypatch.setattr(analytics_service, "_count_by_bucket", _count)

    await analytics_service.daily_revenue_series(
        _StubSession("Africa/Cairo"),
        TENANT,
        since=W1_SINCE,
        until=W1_UNTIL,
    )

    assert seen, "no bucket query ran"
    assert set(seen) == {"Africa/Cairo"}


async def test_the_daily_series_route_labels_the_zone_it_bucketed_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The zone in the response has to be the zone the SQL cut with — one call.

    ``/analytics/daily-series`` is the only reader that builds its own envelope
    instead of passing the service's summary through, and it resolved
    ``?timezone=`` against the DEPLOYMENT before asking the tenant. The service
    then correctly let ``tenants.timezone`` speak, so the buckets landed on
    Cairo days while the response printed the router's own answer as its
    ``timezone``: a Cairo shop served its own numbers under a New York label,
    with no ``timezone_source`` to make the disagreement visible. Pinning the
    emitted label to the recorded bind is what keeps the two from drifting apart
    again — the honest answer to "which zone were these bucketed in" comes from
    the code that bucketed them.
    """
    bucketed: list[str] = []

    async def _sum(session, sql, params):  # noqa: ANN001
        bucketed.append(params["tz"])
        return {}

    monkeypatch.setattr(analytics_service, "_sum_by_bucket", _sum)
    monkeypatch.setattr(analytics_service, "_count_by_bucket", _sum)

    async def _currency(session, tenant_id):  # noqa: ANN001
        return "EGP"

    monkeypatch.setattr(analytics_router, "resolve_tenant_currency", _currency)
    monkeypatch.setenv(REPORTING_TZ_ENV, DEPLOYMENT)

    ctx = SimpleNamespace(tenant_id=TENANT, session=_StubSession("Africa/Cairo"))
    payload = await analytics_router.daily_series(
        ctx=ctx, since=W1_SINCE, until=W1_UNTIL, timezone=None
    )

    assert set(bucketed) == {"Africa/Cairo"}, (
        f"the buckets were cut in {sorted(set(bucketed))}, not the tenant's zone"
    )
    assert payload["timezone"] == "Africa/Cairo"
    assert payload["timezone_source"] == "tenant"


# ================================= the write boundary: refuse, then audit ==


@pytest.mark.parametrize("zone", ["Africa/Cairo", "Europe/London", "UTC", "Asia/Dubai"])
def test_an_iana_zone_this_runtime_resolves_is_accepted(zone: str) -> None:
    assert identity_service.timezone_refusal(zone) is None


@pytest.mark.parametrize(
    "zone", ["Mars/Olympus_Mons", "Africa/Cairo/Extra", "not a zone", "Etc/Strange", "x" * 40]
)
def test_a_zone_that_is_not_one_resolvable_iana_name_is_refused(zone: str) -> None:
    """Same posture as an unknown currency code (§47): the answer is a refusal
    with a reason, never a stored value that every reader then trips over."""
    assert identity_service.timezone_refusal(zone) is not None


def test_a_zone_longer_than_the_column_is_refused() -> None:
    """The DB check bounds the SHAPE; this bounds it identically, so an owner
    gets a 400 with a reason instead of a 500 from the constraint."""
    assert identity_service.timezone_refusal("Africa/" + "C" * 60) is not None


# ============================== the surface an owner actually calls =========


def test_the_timezone_write_route_is_registered() -> None:
    assert any(
        r.path == TIMEZONE_PATH and "PUT" in r.methods for r in tenants_router.routes
    ), f"PUT {TIMEZONE_PATH} must be routed on tenants_router"


def test_the_timezone_read_route_is_registered() -> None:
    assert any(
        r.path == TIMEZONE_PATH and "GET" in r.methods for r in tenants_router.routes
    ), f"GET {TIMEZONE_PATH} must be routed on tenants_router"


def test_the_timezone_routes_are_gated_like_the_currency_routes() -> None:
    """Same permission pair as the currency setting — a write is settings:write,
    a read is settings:read, and both are declared at the ROUTE."""
    assert _permission_codes(tenants_router.routes, TIMEZONE_PATH, "PUT") == {"settings:write"}
    assert _permission_codes(tenants_router.routes, TIMEZONE_PATH, "GET") == {"settings:read"}


def test_the_currency_read_route_is_still_gated() -> None:
    """§47's read must survive the sibling being added beside it."""
    assert _permission_codes(
        tenants_router.routes, "/tenants/{tenant_id}/currency", "GET"
    ) == {"settings:read"}


# ======================================================= the schema ---------


def _migration_revisions() -> dict[str, str | None]:
    """revision -> down_revision for every migration script."""
    found: dict[str, str | None] = {}
    for path in sorted(VERSIONS_DIR.glob("*.py")):
        if path.name.startswith("__"):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        revision: str | None = None
        down: str | None = None
        for node in tree.body:
            if not isinstance(node, ast.AnnAssign | ast.Assign):
                continue
            value = node.value
            if not isinstance(value, ast.Constant):
                continue
            targets = [node.target] if isinstance(node, ast.AnnAssign) else node.targets
            for target in targets:
                name = getattr(target, "id", None)
                if name == "revision":
                    revision = str(value.value)
                elif name == "down_revision":
                    down = None if value.value is None else str(value.value)
        assert revision, f"{path.name} declares no revision id"
        found[revision] = down
    return found


def test_exactly_one_migration_head() -> None:
    """`alembic heads` must print one id: two heads abort the deploy."""
    revisions = _migration_revisions()
    parents = {down for down in revisions.values() if down}
    heads = sorted(r for r in revisions if r not in parents)
    assert len(heads) == 1, f"migration heads: {heads}"


def test_the_tenant_zone_descends_from_the_previous_head() -> None:
    """An applied revision is IMMUTABLE: the new column arrives in a NEW
    revision whose down_revision is the head that existed before it."""
    revisions = _migration_revisions()
    children = sorted(r for r, down in revisions.items() if down == PREVIOUS_HEAD)
    assert len(children) == 1, f"{PREVIOUS_HEAD} has {len(children)} children: {children}"
    assert f'revision: str = "{children[0]}"' in _zone_migration()


def test_the_tenant_zone_column_is_nullable_and_unbackfilled() -> None:
    """NULL means "no opinion, use the deployment zone". A server_default or an
    UPDATE here would GUESS a zone for every live tenant and silently move
    every day bucket they have ever read."""
    from app.core.model_registry import Base

    column = Base.metadata.tables["tenants"].c["timezone"]
    assert column.nullable is True
    assert column.server_default is None

    upgrade = _zone_migration().split("def upgrade", 1)[1].split("def downgrade", 1)[0]
    assert "server_default" not in upgrade
    assert "UPDATE tenants" not in upgrade.upper()


def test_the_column_carries_a_shape_check_and_says_why() -> None:
    """The CHECK is NOT NULL-shape sanity only: proving a name resolves to an
    IANA zone needs tzdata, which lives in Python (`zoneinfo`), not in the
    database. The write boundary is where resolvability is asserted."""
    source = _zone_migration()
    assert "create_check_constraint" in source
    assert "timezone IS NULL" in source.replace('"timezone"', "timezone")
    assert "zoneinfo" in source.lower(), "the migration must say why it checks shape only"
    # The downgrade removes what the upgrade added, in the same order it appeared.
    downgrade = source.split("def downgrade", 1)[1]
    assert "drop_constraint" in downgrade and "drop_column" in downgrade


# ============================================ driven over a real database ===


def _client(db: AsyncSession, *, ctx_tenant_id: uuid.UUID, perms: set[str]) -> AsyncClient:
    """The real ASGI stack with ONLY the auth context swapped, so the route, its
    gate and its tenant-match rule are the things under test."""
    app: FastAPI = create_app()

    async def _ctx() -> TenantContext:
        return TenantContext(
            session=db,
            user=AuthedUser(id=uuid.uuid4(), tenant_id=ctx_tenant_id, role_code="owner"),
            tenant_id=ctx_tenant_id,
            role_code="owner",
            permission_codes=perms,
        )

    app.dependency_overrides[get_tenant_ctx] = _ctx
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_the_owner_can_set_the_day_zone(db: AsyncSession, tenant_ctx) -> None:
    tenant = await TenantSettingsService.set_timezone(
        db, tenant_ctx.tenant_id, "Africa/Cairo", actor_user_id=tenant_ctx.user.id
    )
    assert tenant.timezone == "Africa/Cairo"


async def test_setting_the_same_zone_twice_writes_one_audit_row(
    db: AsyncSession, tenant_ctx
) -> None:
    """An idempotent PUT must not claim a change it did not make."""
    from app.modules.platform.models import AuditLog

    await TenantSettingsService.set_timezone(
        db, tenant_ctx.tenant_id, "Africa/Cairo", actor_user_id=tenant_ctx.user.id
    )
    await TenantSettingsService.set_timezone(
        db, tenant_ctx.tenant_id, " Africa/Cairo ", actor_user_id=tenant_ctx.user.id
    )
    await db.flush()

    rows = (
        await db.execute(
            sa.select(AuditLog).where(
                AuditLog.tenant_id == tenant_ctx.tenant_id,
                AuditLog.action == "tenant.timezone_changed",
            )
        )
    ).scalars().all()
    assert len(rows) == 1


async def test_an_unresolvable_zone_is_refused_and_not_stored(
    db: AsyncSession, tenant_ctx
) -> None:
    with pytest.raises(ValidationError, match="Mars/Olympus_Mons"):
        await TenantSettingsService.set_timezone(
            db, tenant_ctx.tenant_id, "Mars/Olympus_Mons", actor_user_id=tenant_ctx.user.id
        )
    await db.flush()
    stored = (
        await db.execute(sa.select(Tenant).where(Tenant.id == tenant_ctx.tenant_id))
    ).scalar_one()
    assert stored.timezone is None


async def test_the_zone_change_leaves_an_audit_row(db: AsyncSession, tenant_ctx) -> None:
    from app.modules.platform.models import AuditLog

    await TenantSettingsService.set_timezone(
        db, tenant_ctx.tenant_id, "Asia/Dubai", actor_user_id=tenant_ctx.user.id
    )
    await db.flush()

    row = (
        await db.execute(
            sa.select(AuditLog).where(
                AuditLog.tenant_id == tenant_ctx.tenant_id,
                AuditLog.action == "tenant.timezone_changed",
            )
        )
    ).scalar_one()
    assert row.before == {"timezone": None}
    assert row.after == {"timezone": "Asia/Dubai"}
    assert row.actor_user_id == tenant_ctx.user.id
    # §66 lineage: source / request_id are stamped by the edge middleware and
    # the audit writer, never by the caller.
    assert row.source == "human"


async def test_clearing_the_zone_returns_the_tenant_to_the_deployment(
    db: AsyncSession, tenant_ctx
) -> None:
    """NULL is a real setting: it is how an owner says "no opinion"."""
    await TenantSettingsService.set_timezone(
        db, tenant_ctx.tenant_id, "Asia/Dubai", actor_user_id=tenant_ctx.user.id
    )
    tenant = await TenantSettingsService.set_timezone(
        db, tenant_ctx.tenant_id, "", actor_user_id=tenant_ctx.user.id
    )
    assert tenant.timezone is None


async def test_the_settings_route_sets_and_reads_the_zone(
    db: AsyncSession, tenant_ctx
) -> None:
    async with _client(db, ctx_tenant_id=tenant_ctx.tenant_id, perms={"settings:write"}) as client:
        written = await client.put(
            f"/api/v1/tenants/{tenant_ctx.tenant_id}/timezone",
            json={"timezone": "Africa/Cairo"},
        )
    assert written.status_code == 200, written.text
    assert written.json() == {
        "tenant_id": str(tenant_ctx.tenant_id),
        "timezone": "Africa/Cairo",
    }

    async with _client(db, ctx_tenant_id=tenant_ctx.tenant_id, perms={"settings:read"}) as client:
        read = await client.get(f"/api/v1/tenants/{tenant_ctx.tenant_id}/timezone")
    assert read.status_code == 200, read.text
    body: dict[str, Any] = read.json()
    assert body == {"tenant_id": str(tenant_ctx.tenant_id), "timezone": "Africa/Cairo"}


async def test_the_settings_route_reports_no_zone_as_null(
    db: AsyncSession, tenant_ctx, monkeypatch
) -> None:
    """NULL is the tenant's own answer, and the screen renders it as "system
    default". The EFFECTIVE zone is not this route's to invent: it comes back on
    every analytics response as `timezone` + `timezone_source`, which is the
    layer that actually bucketed the numbers the merchant is looking at."""
    monkeypatch.setenv(REPORTING_TZ_ENV, DEPLOYMENT)
    async with _client(db, ctx_tenant_id=tenant_ctx.tenant_id, perms={"settings:read"}) as client:
        read = await client.get(f"/api/v1/tenants/{tenant_ctx.tenant_id}/timezone")

    assert read.status_code == 200, read.text
    assert read.json() == {"tenant_id": str(tenant_ctx.tenant_id), "timezone": None}


async def test_a_route_refuses_a_zone_it_cannot_resolve(db: AsyncSession, tenant_ctx) -> None:
    async with _client(db, ctx_tenant_id=tenant_ctx.tenant_id, perms={"settings:write"}) as client:
        response = await client.put(
            f"/api/v1/tenants/{tenant_ctx.tenant_id}/timezone",
            json={"timezone": "Mars/Olympus_Mons"},
        )
    assert response.status_code == 400, response.text


async def test_another_tenants_caller_cannot_set_the_zone(
    db: AsyncSession, tenant_ctx
) -> None:
    async with _client(db, ctx_tenant_id=uuid.uuid4(), perms={"settings:write"}) as client:
        response = await client.put(
            f"/api/v1/tenants/{tenant_ctx.tenant_id}/timezone",
            json={"timezone": "Africa/Cairo"},
        )
    assert response.status_code == 403, response.text


async def test_a_writer_without_the_permission_is_refused(
    db: AsyncSession, tenant_ctx
) -> None:
    async with _client(db, ctx_tenant_id=tenant_ctx.tenant_id, perms={"settings:read"}) as client:
        response = await client.put(
            f"/api/v1/tenants/{tenant_ctx.tenant_id}/timezone",
            json={"timezone": "Africa/Cairo"},
        )
    assert response.status_code == 403, response.text


async def test_a_tenant_with_its_own_zone_gets_its_own_day_labels(
    db: AsyncSession, tenant_ctx, monkeypatch
) -> None:
    """THE case this gap exists for, CI-only.

    One instant — 22:30 UTC on 14 March — is 00:30 on the 15th in Cairo and
    still the 14th in New York. The tenant that declared Cairo gets the 15th;
    the tenant that declared nothing keeps the deployment's answer. Same
    window, same query, no caller-supplied zone.
    """
    from app.core.db import bind_tenant

    monkeypatch.setenv(REPORTING_TZ_ENV, DEPLOYMENT)
    paid_at = datetime(2026, 3, 14, 22, 30, tzinfo=UTC)

    cairo = tenant_ctx.tenant_id
    await TenantSettingsService.set_timezone(
        db, cairo, "Africa/Cairo", actor_user_id=tenant_ctx.user.id
    )
    await _collected(db, cairo, amount="70.00", paid_at=paid_at)

    own_rows = await analytics_service.daily_revenue_series(
        db, cairo, since=W1_SINCE, until=W1_UNTIL
    )
    own_summary = await analytics_service.revenue_summary(
        db, cairo, since=W1_SINCE, until=W1_UNTIL
    )
    assert [r["day"] for r in own_rows] == ["2026-03-15"]
    assert own_summary["timezone"] == "Africa/Cairo"
    assert own_summary["timezone_source"] == "tenant"

    # A second tenant, no column, the same instant: the deployment still answers.
    plain = Tenant(slug=f"plain-{uuid.uuid4().hex[:10]}", name="No Zone Tenant")
    db.add(plain)
    await db.flush()
    await bind_tenant(db, plain.id)
    await _collected(db, plain.id, amount="70.00", paid_at=paid_at)

    other_rows = await analytics_service.daily_revenue_series(
        db, plain.id, since=W1_SINCE, until=W1_UNTIL
    )
    other_summary = await analytics_service.revenue_summary(
        db, plain.id, since=W1_SINCE, until=W1_UNTIL
    )
    assert [r["day"] for r in other_rows] == ["2026-03-14"]
    assert other_summary["timezone"] == DEPLOYMENT
    assert other_summary["timezone_source"] == "deployment"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
