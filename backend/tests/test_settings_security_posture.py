"""Section 18's session-control page reads a posture, and the posture must be true.

The page cannot own a session-policy editor: the token lifetimes are deployment
configuration and no registry key holds them. So it reads ``GET /settings/security-posture``,
which reports the four ``security.*`` values the running code enforces plus the two
lifetimes the process was started with.

Two things are worth pinning here, because both are the kind of lie a posture screen
tells easily:

* the values are the RESOLVED ones (an override at tenant scope wins over the registry
  default), not the defaults rendered as if they were in force;
* the IP allowlist is reported as a count. The value is SENSITIVE and this route is not
  the place that hands the entries out — a page that showed them would leak the shop's
  perimeter to anyone holding ``settings:read``.
"""

from __future__ import annotations

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.main import create_app
from app.platform.identity.deps import AuthedUser, TenantContext, get_tenant_ctx
from app.platform.settings.service import SettingsService

POSTURE_URL = "/api/v1/settings/security-posture"


def _client(db: AsyncSession, ctx: TenantContext) -> AsyncClient:
    app: FastAPI = create_app()

    async def _ctx() -> TenantContext:
        return TenantContext(
            session=db,
            user=AuthedUser(id=ctx.user.id, tenant_id=ctx.tenant_id, role_code="owner"),
            tenant_id=ctx.tenant_id,
            role_code="owner",
            permission_codes={"settings:read"},
        )

    app.dependency_overrides[get_tenant_ctx] = _ctx
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_posture_reports_the_registry_defaults_when_nothing_is_overridden(
    db: AsyncSession, tenant_ctx
) -> None:
    async with _client(db, tenant_ctx) as client:
        response = await client.get(POSTURE_URL)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["password_policy"]["require_strong_passwords"] is True
    assert body["api_keys"]["rotation_days"] == 90
    assert body["audit"]["retention_days"] == 365
    assert body["ip_allowlist"] == {"configured": False, "entries": 0}


async def test_an_override_at_tenant_scope_is_what_the_posture_reports(
    db: AsyncSession, tenant_ctx
) -> None:
    service = SettingsService(db, tenant_ctx.tenant_id)
    await service.set(
        "security.require_strong_passwords", False, scope="tenant", bypass_approval=True
    )
    await service.set("security.audit_retention_days", 30, scope="tenant", bypass_approval=True)
    await db.flush()

    async with _client(db, tenant_ctx) as client:
        response = await client.get(POSTURE_URL)

    body = response.json()
    assert body["password_policy"]["require_strong_passwords"] is False
    assert body["audit"]["retention_days"] == 30


async def test_the_allowlist_is_counted_and_never_echoed(db: AsyncSession, tenant_ctx) -> None:
    service = SettingsService(db, tenant_ctx.tenant_id)
    await service.set(
        "security.ip_allowlist",
        ["203.0.113.7", "10.0.0.0/8"],
        scope="tenant",
        bypass_approval=True,
    )
    await db.flush()

    async with _client(db, tenant_ctx) as client:
        response = await client.get(POSTURE_URL)

    body = response.json()
    assert body["ip_allowlist"] == {"configured": True, "entries": 2}
    assert "203.0.113.7" not in response.text, "the allowlist entries must not leave the server"


async def test_the_token_lifetimes_come_from_the_running_configuration(
    db: AsyncSession, tenant_ctx
) -> None:
    config = get_settings()

    async with _client(db, tenant_ctx) as client:
        response = await client.get(POSTURE_URL)

    sessions = response.json()["sessions"]
    assert sessions["access_token_ttl_seconds"] == int(config.access_token_ttl_seconds)
    assert sessions["refresh_token_ttl_seconds"] == int(config.refresh_token_ttl_seconds)


async def test_the_route_is_gated_by_settings_read(db: AsyncSession, tenant_ctx) -> None:
    app: FastAPI = create_app()

    async def _ctx() -> TenantContext:
        return TenantContext(
            session=db,
            user=AuthedUser(
                id=tenant_ctx.user.id, tenant_id=tenant_ctx.tenant_id, role_code="staff"
            ),
            tenant_id=tenant_ctx.tenant_id,
            role_code="staff",
            permission_codes=set(),
        )

    app.dependency_overrides[get_tenant_ctx] = _ctx
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(POSTURE_URL)

    assert response.status_code == 403
