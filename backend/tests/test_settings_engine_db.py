"""The settings engine against a real PostgreSQL, as ``sales_app`` with RLS enforced.

``test_settings_engine.py`` mocks the session, so it cannot see any of what matters
here: the unique key with a NULL scope id, the inheritance chain read from the real
hierarchy, tenant isolation, the per-key permission, or the audit rows. A skipped
database test proves nothing, so these fail loudly when the database is missing the
tables rather than passing on a mock.
"""

from __future__ import annotations

import dataclasses
import uuid

import pytest
import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import IntegrityError

from app.core.errors import NotFoundError, PermissionDeniedError, ValidationError
from app.modules.identity.models import Location, Workspace
from app.modules.pos.profiles import PosProfileService
from app.modules.settings.models import TenantSetting
from app.modules.settings.registry import Scope
from app.modules.settings.service import SettingsService
from tests._pos_helpers import ctx_for
from tests.test_pos_returns import _register, _warehouse
from tests.test_pos_sale_http import _app

pytestmark = pytest.mark.asyncio

OWNER = {"settings:read", "settings:write", "settings:branch_write"}
MANAGER = {"settings:read", "settings:branch_write"}
STAFF = {"settings:read"}


# --------------------------------------------------------------------------- hierarchy


@dataclasses.dataclass
class Shop:
    branch_a: uuid.UUID
    branch_b: uuid.UUID
    warehouse: uuid.UUID
    profile: uuid.UUID
    register: uuid.UUID


async def _shop(db, tenant_ctx) -> Shop:
    """Two branches; the default warehouse sits in branch A, with a profile and a register."""
    ws = Workspace(tenant_id=tenant_ctx.tenant_id, name="main", slug=f"w{uuid.uuid4().hex[:6]}")
    db.add(ws)
    await db.flush()
    a = Location(tenant_id=tenant_ctx.tenant_id, workspace_id=ws.id, name="Cairo", code="CAI")
    b = Location(tenant_id=tenant_ctx.tenant_id, workspace_id=ws.id, name="Giza", code="GIZ")
    db.add_all([a, b])
    await db.flush()

    wh = await _warehouse(db, tenant_ctx)
    await db.execute(
        sa.text("UPDATE warehouses SET location_id = :loc WHERE id = :id"),
        {"loc": a.id, "id": wh.id},
    )
    profile = await PosProfileService.create(
        db,
        tenant_ctx.tenant_id,
        name="p",
        code=f"P{uuid.uuid4().hex[:5]}",
        warehouse_id=wh.id,
        allowed_payment_methods=["cash"],
    )
    register = await _register(db, tenant_ctx)
    await db.execute(
        sa.text("UPDATE pos_registers SET profile_id = :p WHERE id = :id"),
        {"p": profile.id, "id": register.id},
    )
    return Shop(a.id, b.id, wh.id, profile.id, register.id)


# --------------------------------------------------------------------------- uniqueness


async def test_two_tenant_level_rows_for_one_key_are_impossible(db, tenant_ctx) -> None:
    """NULL scope_id used to slip past the unique key, then every read raised."""
    for value in (10, 99):
        db.add(
            TenantSetting(
                tenant_id=tenant_ctx.tenant_id,
                key="pos.max_discount_pct",
                scope="tenant",
                scope_id=None,
                value={"v": value},
            )
        )
        if value == 10:
            await db.flush()
    with pytest.raises(IntegrityError):
        await db.flush()


async def test_a_non_tenant_row_must_carry_its_scope_id(db, tenant_ctx) -> None:
    db.add(
        TenantSetting(
            tenant_id=tenant_ctx.tenant_id,
            key="pos.max_discount_pct",
            scope="branch",
            scope_id=None,
            value={"v": 5},
        )
    )
    with pytest.raises(IntegrityError):
        await db.flush()


async def test_setting_twice_updates_one_row(db, tenant_ctx) -> None:
    svc = SettingsService(db, tenant_ctx.tenant_id)
    await svc.set("pos.max_discount_pct", 10)
    await svc.set("pos.max_discount_pct", 12)
    rows = await svc.list_overrides(domain="pos")
    assert [(r.key, r.value) for r in rows] == [("pos.max_discount_pct", {"v": 12.0})]


# --------------------------------------------------------------------------- inheritance


async def test_chain_is_read_from_the_database_not_the_caller(db, tenant_ctx) -> None:
    shop = await _shop(db, tenant_ctx)
    svc = SettingsService(db, tenant_ctx.tenant_id)
    key = "pos.max_discount_pct"

    await svc.set(key, 10)  # tenant
    r = await svc.resolve(key, scope=Scope.REGISTER, scope_id=shop.register)
    assert (r.value, r.scope, r.is_inherited) == (10.0, "tenant", True)

    await svc.set(key, 15, scope=Scope.BRANCH, scope_id=shop.branch_a)
    r = await svc.resolve(key, scope=Scope.REGISTER, scope_id=shop.register)
    assert (r.value, r.scope, r.scope_id) == (15.0, "branch", shop.branch_a)

    # The profile is stricter than its branch: the nearest scope wins.
    await svc.set(key, 5, scope=Scope.POS_PROFILE, scope_id=shop.profile)
    r = await svc.resolve(key, scope=Scope.REGISTER, scope_id=shop.register)
    assert (r.value, r.scope, r.scope_id) == (5.0, "pos_profile", shop.profile)
    assert r.is_inherited is True

    own = await svc.resolve(key, scope=Scope.POS_PROFILE, scope_id=shop.profile)
    assert own.is_inherited is False


async def test_another_branchs_override_never_leaks(db, tenant_ctx) -> None:
    shop = await _shop(db, tenant_ctx)
    svc = SettingsService(db, tenant_ctx.tenant_id)
    key = "pos.max_discount_pct"
    await svc.set(key, 10)
    await svc.set(key, 50, scope=Scope.BRANCH, scope_id=shop.branch_b)  # Giza only

    cairo = await svc.resolve(key, scope=Scope.BRANCH, scope_id=shop.branch_a)
    giza = await svc.resolve(key, scope=Scope.BRANCH, scope_id=shop.branch_b)
    via_register = await svc.resolve(key, scope=Scope.REGISTER, scope_id=shop.register)
    assert cairo.value == 10.0
    assert giza.value == 50.0
    assert via_register.value == 10.0  # register -> ... -> Cairo, not Giza


async def test_reset_restores_the_inherited_value(db, tenant_ctx) -> None:
    shop = await _shop(db, tenant_ctx)
    svc = SettingsService(db, tenant_ctx.tenant_id)
    key = "pos.max_discount_pct"
    await svc.set(key, 10)
    await svc.set(key, 15, scope=Scope.BRANCH, scope_id=shop.branch_a)
    assert await svc.reset(key, scope=Scope.BRANCH, scope_id=shop.branch_a) is True
    assert await svc.reset(key, scope=Scope.BRANCH, scope_id=shop.branch_a) is False
    r = await svc.resolve(key, scope=Scope.BRANCH, scope_id=shop.branch_a)
    assert (r.value, r.scope, r.is_inherited) == (10.0, "tenant", True)


async def test_a_scope_entity_must_exist_for_this_tenant(db, tenant_ctx) -> None:
    svc = SettingsService(db, tenant_ctx.tenant_id)
    with pytest.raises(NotFoundError):
        await svc.set("pos.max_discount_pct", 5, scope=Scope.BRANCH, scope_id=uuid.uuid4())
    with pytest.raises(NotFoundError):
        await svc.resolve("pos.max_discount_pct", scope=Scope.BRANCH, scope_id=uuid.uuid4())
    with pytest.raises(NotFoundError):  # a non-tenant scope without an id
        await svc.set("pos.max_discount_pct", 5, scope=Scope.BRANCH, scope_id=None)


async def test_bad_input_is_a_validation_error_not_a_crash(db, tenant_ctx) -> None:
    svc = SettingsService(db, tenant_ctx.tenant_id)
    with pytest.raises(ValidationError):
        await svc.set("pos.max_discount_pct", "ten")
    with pytest.raises(ValidationError):
        await svc.set("pos.max_discount_pct", 500)  # above the maximum
    with pytest.raises(ValidationError):
        await svc.set("no.such.key", 1)
    with pytest.raises(ValidationError):  # business.tax_id is tenant-only
        shop = await _shop(db, tenant_ctx)
        await svc.set("business.tax_id", "1", scope=Scope.BRANCH, scope_id=shop.branch_a)


async def test_bulk_set_writes_nothing_when_one_key_is_bad(db, tenant_ctx) -> None:
    svc = SettingsService(db, tenant_ctx.tenant_id)
    with pytest.raises(ValidationError):
        await svc.bulk_set({"pos.max_discount_pct": 10, "pos.require_customer": "yes"})
    assert await svc.list_overrides() == []


# --------------------------------------------------------------------------- permissions


async def test_manager_sets_a_delegable_key_on_a_branch_but_never_on_the_tenant(
    db, tenant_ctx
) -> None:
    shop = await _shop(db, tenant_ctx)
    svc = SettingsService(db, tenant_ctx.tenant_id)
    uid = tenant_ctx.user.id

    await svc.set(
        "pos.max_discount_pct",
        8,
        scope=Scope.BRANCH,
        scope_id=shop.branch_a,
        user_id=uid,
        permissions=MANAGER,
    )
    with pytest.raises(PermissionDeniedError):
        await svc.set("pos.max_discount_pct", 8, user_id=uid, permissions=MANAGER)


async def test_manager_cannot_touch_an_owner_only_key_anywhere(db, tenant_ctx) -> None:
    shop = await _shop(db, tenant_ctx)
    svc = SettingsService(db, tenant_ctx.tenant_id)
    for scope, sid in ((Scope.TENANT, None), (Scope.BRANCH, shop.branch_a)):
        with pytest.raises(PermissionDeniedError):
            await svc.set(
                "purchasing.approval_required",
                True,
                scope=scope,
                scope_id=sid,
                user_id=tenant_ctx.user.id,
                permissions=MANAGER,
            )


async def test_staff_can_write_nothing_but_their_own_preference(db, tenant_ctx) -> None:
    svc = SettingsService(db, tenant_ctx.tenant_id)
    uid = tenant_ctx.user.id
    with pytest.raises(PermissionDeniedError):
        await svc.set("pos.max_discount_pct", 5, user_id=uid, permissions=STAFF)
    await svc.set(
        "notifications.order_received",
        False,
        scope=Scope.USER,
        scope_id=uid,
        user_id=uid,
        permissions=STAFF,
    )


async def test_http_roles_get_the_right_status(db, tenant_ctx) -> None:
    shop = await _shop(db, tenant_ctx)
    url = "/api/v1/settings/pos.max_discount_pct"
    branch_body = {"value": 7, "scope": "branch", "scope_id": str(shop.branch_a)}
    tenant_body = {"value": 7}

    async def put(role, body):
        ctx = await ctx_for(db, tenant_ctx, role)
        async with AsyncClient(transport=ASGITransport(app=_app(ctx)), base_url="http://t") as c:
            return await c.put(url, json=body)

    assert (await put("staff", branch_body)).status_code == 403
    assert (await put("manager", branch_body)).status_code == 200
    assert (await put("manager", tenant_body)).status_code == 403
    assert (await put("owner", tenant_body)).status_code == 200
    bad = await put("owner", {"value": "x"})
    assert bad.status_code == 400, bad.text
    unknown = await put("owner", {"value": 1, "scope": "branch", "scope_id": str(uuid.uuid4())})
    assert unknown.status_code == 404, unknown.text


# --------------------------------------------------------------------------- audit


async def test_every_change_is_in_history_and_audited_keys_reach_audit_logs(db, tenant_ctx) -> None:
    svc = SettingsService(db, tenant_ctx.tenant_id)
    uid = tenant_ctx.user.id
    await svc.set("pos.max_discount_pct", 10, user_id=uid, reason="opening")
    await svc.set("pos.max_discount_pct", 12, user_id=uid)
    await svc.set("pos.max_discount_pct", 12, user_id=uid)  # same value: no new record
    await svc.reset("pos.max_discount_pct", user_id=uid, reason="back to default")

    hist = await svc.history(key="pos.max_discount_pct")
    assert [(h.action, h.old_value, h.new_value) for h in reversed(hist)] == [
        ("set", None, {"v": 10.0}),
        ("set", {"v": 10.0}, {"v": 12.0}),
        ("reset", {"v": 12.0}, None),
    ]
    assert hist[0].changed_by == uid
    assert hist[0].change_reason == "back to default"

    rows = (
        await db.execute(
            sa.text(
                "SELECT action, before, after, resource_id FROM audit_logs "
                "WHERE tenant_id = :t AND resource_type = 'tenant_setting' ORDER BY created_at"
            ),
            {"t": tenant_ctx.tenant_id},
        )
    ).all()
    # Read the rows by CONTENT, not by position. All four calls above run in one transaction and
    # `audit_logs.created_at` is `now()`, which Postgres fixes at transaction start: the three rows
    # share a timestamp, so `ORDER BY created_at` cannot order them and asserting rows[0] was a
    # coin toss (it failed exactly that way on main's CI run 45903956902, shard 4). What matters is
    # that each change produced one row carrying the value as it stood at that moment.
    assert sorted(r.action for r in rows) == ["settings.reset", "settings.set", "settings.set"]
    assert sorted(r.after["value"]["v"] for r in rows if r.action == "settings.set") == [10.0, 12.0]
    first = next(r for r in rows if r.action == "settings.set" and r.after["value"] == {"v": 10.0})
    assert first.after == {
        "key": "pos.max_discount_pct",
        "scope": "tenant",
        "scope_id": None,
        "value": {"v": 10.0},
    }
    # a reset keeps what was removed, so the row explains itself after the setting is gone
    reset = next(r for r in rows if r.action == "settings.reset")
    assert reset.before["value"] == {"v": 12.0}
    assert reset.after["value"] is None


async def test_an_unaudited_key_stays_out_of_audit_logs(db, tenant_ctx) -> None:
    svc = SettingsService(db, tenant_ctx.tenant_id)
    await svc.set("print.copies", 2, user_id=tenant_ctx.user.id)
    n = (
        await db.execute(
            sa.text(
                "SELECT count(*) FROM audit_logs "
                "WHERE tenant_id = :t AND resource_type = 'tenant_setting'"
            ),
            {"t": tenant_ctx.tenant_id},
        )
    ).scalar_one()
    assert n == 0
    assert len(await svc.history(key="print.copies")) == 1


# --------------------------------------------------------------------------- isolation


async def test_one_tenant_never_sees_another_tenants_settings(db, tenant_ctx) -> None:
    from app.core.db import bind_tenant
    from app.modules.identity.models import Tenant

    svc = SettingsService(db, tenant_ctx.tenant_id)
    await svc.set("pos.max_discount_pct", 33)

    other = Tenant(slug=f"o-{uuid.uuid4().hex[:8]}", name="Other")
    db.add(other)
    await db.flush()
    await bind_tenant(db, other.id)

    theirs = SettingsService(db, other.id)
    assert (await theirs.resolve("pos.max_discount_pct")).is_default is True
    assert await theirs.list_overrides() == []
    assert await theirs.history() == []


# ------------------------------------------------------------- wired to the orders flow


async def test_the_reservation_hold_follows_the_ttl_setting(db, tenant_ctx) -> None:
    """The hold an order takes lasts what ``inventory.reserve_ttl_minutes`` says, and a shop
    that never set it keeps the 15 minutes the order flow has always used."""
    from datetime import timedelta

    from app.modules.orders.service import _RESERVATION_TTL, reservation_ttl

    assert _RESERVATION_TTL == timedelta(minutes=15)
    assert await reservation_ttl(db, tenant_ctx.tenant_id) == _RESERVATION_TTL

    await SettingsService(db, tenant_ctx.tenant_id).set("inventory.reserve_ttl_minutes", 120)
    assert await reservation_ttl(db, tenant_ctx.tenant_id) == timedelta(minutes=120)
