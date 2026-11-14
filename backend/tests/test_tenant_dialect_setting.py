"""The shop owner sets the assistant's dialect: service, audit and routes.

Mirrors the timezone setting's posture. The write is refused for anything off the closed list,
audited with before and after, idempotent (a repeat is not a change), and clearable (empty puts the
shop back on the currency's dialect). The read says BOTH what the owner stored and what the
assistant will actually use, with where that came from, because "null" alone would leave the screen
unable to say "answers in Egyptian, from your currency".
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationError
from app.main import create_app
from app.modules.identity.deps import AuthedUser, TenantContext, get_tenant_ctx
from app.modules.identity.models import Tenant
from app.modules.identity.router import tenants_router
from app.modules.identity.service import TenantSettingsService

PATH = "/tenants/{tenant_id}/dialect"


def _permission_codes(routes, path: str, method: str) -> set[str]:
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


def test_the_routes_exist_and_are_gated_like_the_timezone_ones() -> None:
    assert _permission_codes(tenants_router.routes, PATH, "PUT") == {"settings:write"}
    assert _permission_codes(tenants_router.routes, PATH, "GET") == {"settings:read"}


def _client(
    db: AsyncSession, *, ctx_tenant_id: uuid.UUID, ctx_user_id: uuid.UUID, perms: set[str]
) -> AsyncClient:
    app: FastAPI = create_app()

    async def _ctx() -> TenantContext:
        return TenantContext(
            session=db,
            user=AuthedUser(id=ctx_user_id, tenant_id=ctx_tenant_id, role_code="owner"),
            tenant_id=ctx_tenant_id,
            role_code="owner",
            permission_codes=perms,
        )

    app.dependency_overrides[get_tenant_ctx] = _ctx
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _stored(db: AsyncSession, tenant_id: uuid.UUID) -> str | None:
    await db.flush()
    row = (await db.execute(sa.select(Tenant).where(Tenant.id == tenant_id))).scalar_one()
    await db.refresh(row)
    return row.dialect


async def test_the_owner_can_choose_a_dialect(db: AsyncSession, tenant_ctx) -> None:
    tenant = await TenantSettingsService.set_dialect(
        db, tenant_ctx.tenant_id, "gulf", actor_user_id=tenant_ctx.user.id
    )
    assert tenant.dialect == "gulf"
    assert await _stored(db, tenant_ctx.tenant_id) == "gulf"


@pytest.mark.parametrize("bad", ["Egyptian", "klingon", "gulf ", "<script>", "x" * 40])
async def test_a_value_off_the_list_is_refused_and_not_stored(
    db: AsyncSession, tenant_ctx, bad: str
) -> None:
    with pytest.raises(ValidationError):
        await TenantSettingsService.set_dialect(
            db, tenant_ctx.tenant_id, bad, actor_user_id=tenant_ctx.user.id
        )
    assert await _stored(db, tenant_ctx.tenant_id) is None


async def test_the_change_leaves_an_audit_row_with_before_and_after(
    db: AsyncSession, tenant_ctx
) -> None:
    from app.modules.platform.models import AuditLog

    await TenantSettingsService.set_dialect(
        db, tenant_ctx.tenant_id, "levantine", actor_user_id=tenant_ctx.user.id
    )
    await db.flush()
    row = (
        await db.execute(
            sa.select(AuditLog).where(
                AuditLog.tenant_id == tenant_ctx.tenant_id,
                AuditLog.action == "tenant.dialect_changed",
            )
        )
    ).scalar_one()
    assert row.before == {"dialect": None}
    assert row.after == {"dialect": "levantine"}
    assert row.actor_user_id == tenant_ctx.user.id
    assert row.source == "human"


async def test_choosing_the_same_dialect_twice_writes_one_audit_row(
    db: AsyncSession, tenant_ctx
) -> None:
    from app.modules.platform.models import AuditLog

    for _ in range(2):
        await TenantSettingsService.set_dialect(
            db, tenant_ctx.tenant_id, "msa", actor_user_id=tenant_ctx.user.id
        )
    await db.flush()
    rows = (
        (
            await db.execute(
                sa.select(AuditLog).where(
                    AuditLog.tenant_id == tenant_ctx.tenant_id,
                    AuditLog.action == "tenant.dialect_changed",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1


async def test_empty_clears_the_choice_back_to_the_currency_default(
    db: AsyncSession, tenant_ctx
) -> None:
    await TenantSettingsService.set_dialect(
        db, tenant_ctx.tenant_id, "gulf", actor_user_id=tenant_ctx.user.id
    )
    tenant = await TenantSettingsService.set_dialect(
        db, tenant_ctx.tenant_id, "", actor_user_id=tenant_ctx.user.id
    )
    assert tenant.dialect is None
    assert await _stored(db, tenant_ctx.tenant_id) is None


async def test_an_unknown_tenant_is_not_found(db: AsyncSession, tenant_ctx) -> None:
    from app.core.errors import NotFoundError

    with pytest.raises(NotFoundError):
        await TenantSettingsService.set_dialect(
            db, uuid.uuid4(), "gulf", actor_user_id=tenant_ctx.user.id
        )


async def test_the_read_says_what_is_stored_what_is_used_and_where_it_came_from(
    db: AsyncSession, tenant_ctx
) -> None:
    async def read() -> dict[str, Any]:
        async with _client(
            db,
            ctx_tenant_id=tenant_ctx.tenant_id,
            ctx_user_id=tenant_ctx.user.id,
            perms={"settings:read"},
        ) as client:
            response = await client.get(f"/api/v1/tenants/{tenant_ctx.tenant_id}/dialect")
        assert response.status_code == 200, response.text
        return response.json()

    # nothing chosen: the assistant uses the currency's dialect, and says so
    await db.execute(
        sa.update(Tenant).where(Tenant.id == tenant_ctx.tenant_id).values(currency="SAR")
    )
    body = await read()
    assert body == {
        "tenant_id": str(tenant_ctx.tenant_id),
        "dialect": None,
        "effective": "gulf",
        "source": "currency",
        "choices": ["egyptian", "gulf", "levantine", "maghrebi", "msa"],
    }

    # a currency with no dialect of its own is neutral, and says that too
    await db.execute(
        sa.update(Tenant).where(Tenant.id == tenant_ctx.tenant_id).values(currency="USD")
    )
    body = await read()
    assert (body["effective"], body["source"]) == ("msa", "default")

    # an explicit choice wins over the currency
    await TenantSettingsService.set_dialect(
        db, tenant_ctx.tenant_id, "egyptian", actor_user_id=tenant_ctx.user.id
    )
    body = await read()
    assert (body["dialect"], body["effective"], body["source"]) == (
        "egyptian",
        "egyptian",
        "owner",
    )


async def test_the_write_route_sets_clears_and_refuses(db: AsyncSession, tenant_ctx) -> None:
    url = f"/api/v1/tenants/{tenant_ctx.tenant_id}/dialect"
    async with _client(
        db,
        ctx_tenant_id=tenant_ctx.tenant_id,
        ctx_user_id=tenant_ctx.user.id,
        perms={"settings:write"},
    ) as client:
        ok = await client.put(url, json={"dialect": "maghrebi"})
        assert ok.status_code == 200, ok.text
        assert ok.json()["dialect"] == "maghrebi"
        assert ok.json()["effective"] == "maghrebi"

        cleared = await client.put(url, json={"dialect": ""})
        assert cleared.status_code == 200, cleared.text
        assert cleared.json()["dialect"] is None

        null_clears = await client.put(url, json={"dialect": None})
        assert null_clears.status_code == 200, null_clears.text

        bad = await client.put(url, json={"dialect": "klingon"})
        assert bad.status_code == 400, bad.text

        too_long = await client.put(url, json={"dialect": "x" * 200})
        assert too_long.status_code == 422, too_long.text


async def test_another_tenants_caller_cannot_set_or_read_it(db: AsyncSession, tenant_ctx) -> None:
    url = f"/api/v1/tenants/{tenant_ctx.tenant_id}/dialect"
    async with _client(
        db,
        ctx_tenant_id=uuid.uuid4(),
        ctx_user_id=tenant_ctx.user.id,
        perms={"settings:write", "settings:read"},
    ) as client:
        assert (await client.put(url, json={"dialect": "gulf"})).status_code == 403
        assert (await client.get(url)).status_code == 403
    assert await _stored(db, tenant_ctx.tenant_id) is None


async def test_a_caller_without_the_permission_is_refused(db: AsyncSession, tenant_ctx) -> None:
    url = f"/api/v1/tenants/{tenant_ctx.tenant_id}/dialect"
    async with _client(
        db,
        ctx_tenant_id=tenant_ctx.tenant_id,
        ctx_user_id=tenant_ctx.user.id,
        perms={"settings:read"},
    ) as client:
        assert (await client.put(url, json={"dialect": "gulf"})).status_code == 403
    async with _client(
        db, ctx_tenant_id=tenant_ctx.tenant_id, ctx_user_id=tenant_ctx.user.id, perms=set()
    ) as client:
        assert (await client.get(url)).status_code == 403
    assert await _stored(db, tenant_ctx.tenant_id) is None
