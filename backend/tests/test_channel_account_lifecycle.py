"""§145 channel-account lifecycle enforcement on the integrations upsert.

W0.4: ``Integration.validate_transition`` (platform/models.py) defines the
7-state lifecycle transition table, but it was dead code — the upsert at
``POST /api/v1/integrations`` wrote ``status`` directly and accepted any jump.

These tests pin the enforced contract:

* an illegal transition on an EXISTING row is rejected with the project's
  ``ValidationError`` (400, code ``validation_error``) and the row — config,
  credentials and status — is left untouched;
* a legal transition succeeds;
* a same-status re-upsert (the webhook-credential refresh path) succeeds —
  idempotent re-registration must not fail;
* a legacy pre-§145 ``connected`` row re-registering as ``active`` (the
  migration's canonical mapping) is a no-op, not an illegal jump.

DB-backed (real Postgres, RLS-bound) — skipped locally without
``DATABASE_URL_APP_ADMIN``; runs in CI.
"""

from __future__ import annotations

import uuid

from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import bind_tenant
from app.core.secrets import decrypt_credentials_dict, encrypt_credentials_dict
from app.main import create_app
from app.modules.identity.deps import AuthedUser, TenantContext, get_tenant_ctx
from app.modules.identity.models import Tenant
from app.modules.platform.models import Integration

PROVIDER = "whatsapp"
# This suite pins the generic integration lifecycle independently from the
# provider-verified channel endpoint. Channel rows must use /integrations/connect.
KIND = "oauth"


def _app(db: AsyncSession, tenant_ctx) -> object:
    """The real app with auth/tenant resolution replaced by the bound test ctx.

    Only the tenant dependency is overridden; the route, the lifecycle check
    and the DomainError handler are the production ones.
    """
    app = create_app()
    ctx = TenantContext(
        session=db,
        user=AuthedUser(id=tenant_ctx.user.id, tenant_id=tenant_ctx.tenant_id, role_code="owner"),
        tenant_id=tenant_ctx.tenant_id,
        role_code="owner",
        permission_codes={"settings:write"},
    )

    async def _override() -> TenantContext:
        return ctx

    app.dependency_overrides[get_tenant_ctx] = _override
    return app


def _body(status: str, *, token: str | None = None) -> dict:
    return {
        "provider": PROVIDER,
        "kind": KIND,
        "config": {},
        "credentials": {"token": token or uuid.uuid4().hex},
        "status": status,
    }


async def _get_row(db: AsyncSession, tenant_id) -> Integration:
    return (
        await db.execute(
            select(Integration).where(
                Integration.tenant_id == tenant_id,
                Integration.provider == PROVIDER,
                Integration.kind == KIND,
            )
        )
    ).scalar_one()


async def test_illegal_transition_is_rejected_and_row_is_untouched(
    db: AsyncSession, tenant_ctx
) -> None:
    """``pending -> active`` is not in the table (pending may only go to
    ``connecting``/``disabled``), so the upsert must be a 400, not a write."""
    original_token = uuid.uuid4().hex
    async with AsyncClient(
        transport=ASGITransport(app=_app(db, tenant_ctx)), base_url="http://test"
    ) as client:
        created = await client.post(
            "/api/v1/integrations", json=_body("pending", token=original_token)
        )
        assert created.status_code == 201
        assert created.json()["status"] == "pending"

        rejected = await client.post("/api/v1/integrations", json=_body("active"))

    assert rejected.status_code == 400, "an illegal lifecycle jump is a client error"
    body = rejected.json()["error"]
    assert body["code"] == "validation_error"
    assert "pending" in body["message"] and "active" in body["message"]

    row = await _get_row(db, tenant_ctx.tenant_id)
    assert row.status == "pending", "a rejected transition must not write status"
    # §68: credentials are envelope-encrypted at rest — compare the plaintext.
    assert decrypt_credentials_dict(row.credentials) == {"token": original_token}, (
        "a rejected transition must not write credentials either"
    )


async def test_legal_transition_succeeds(db: AsyncSession, tenant_ctx) -> None:
    """``pending -> connecting -> active`` walks the table's allowed edges."""
    async with AsyncClient(
        transport=ASGITransport(app=_app(db, tenant_ctx)), base_url="http://test"
    ) as client:
        created = await client.post("/api/v1/integrations", json=_body("pending"))
        assert created.status_code == 201

        connecting = await client.post("/api/v1/integrations", json=_body("connecting"))
        assert connecting.status_code == 201
        assert connecting.json()["status"] == "connecting"

        active = await client.post("/api/v1/integrations", json=_body("active"))
        assert active.status_code == 201
        assert active.json()["status"] == "active"

    row = await _get_row(db, tenant_ctx.tenant_id)
    assert row.status == "active"


async def test_same_status_reupsert_is_idempotent(db: AsyncSession, tenant_ctx) -> None:
    """The credential-refresh path re-POSTs the SAME status with new secrets;
    that must keep working — no transition happens, so no check fires."""
    first_token = uuid.uuid4().hex
    refreshed_token = uuid.uuid4().hex
    async with AsyncClient(
        transport=ASGITransport(app=_app(db, tenant_ctx)), base_url="http://test"
    ) as client:
        created = await client.post("/api/v1/integrations", json=_body("active", token=first_token))
        assert created.status_code == 201

        refreshed = await client.post(
            "/api/v1/integrations", json=_body("active", token=refreshed_token)
        )

    assert refreshed.status_code == 201
    assert refreshed.json()["status"] == "active"
    row = await _get_row(db, tenant_ctx.tenant_id)
    assert decrypt_credentials_dict(row.credentials) == {"token": refreshed_token}, (
        "the refresh must still update credentials"
    )


async def test_legacy_connected_row_reregistering_as_active_is_a_noop(
    db: AsyncSession, tenant_ctx
) -> None:
    """Rows born before §145 (or via the body's legacy default) carry
    ``connected``; the migration maps it to ``active``. Re-registering such a
    row as ``active`` is the same canonical state — it must not be rejected
    as an illegal jump from a state the table does not name."""
    async with AsyncClient(
        transport=ASGITransport(app=_app(db, tenant_ctx)), base_url="http://test"
    ) as client:
        # IntegrationBody.status defaults to the legacy "connected".
        created = await client.post(
            "/api/v1/integrations",
            json={"provider": PROVIDER, "kind": KIND, "credentials": {}},
        )
        assert created.status_code == 201
        assert created.json()["status"] == "connected"

        reregistered = await client.post("/api/v1/integrations", json=_body("active"))

    assert reregistered.status_code == 201
    row = await _get_row(db, tenant_ctx.tenant_id)
    assert row.status == "active"


# --------------------------------------------------------------------------
# Package 5.1 — checklist 5: account lifecycle on the CHANNEL surface.
# A channel row is tenant property: verify/disconnect answer 404 for a row
# another tenant owns, disconnect needs an explicit confirmation, and a
# disconnected channel stops receiving provider traffic entirely (the ingress
# resolver only matches active/connected rows).
# --------------------------------------------------------------------------


async def _channel_row(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    provider: str = "whatsapp",
    status: str = "active",
    config: dict | None = None,
) -> Integration:
    """A kind='channel' integration row, created under the tenant's own GUC."""
    row = Integration(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        provider=provider,
        kind="channel",
        status=status,
        config=config or {},
        credentials=encrypt_credentials_dict({"access_token": uuid.uuid4().hex}),
    )
    db.add(row)
    await db.flush()
    return row


async def test_verify_and_disconnect_refuse_a_row_another_tenant_owns(
    db: AsyncSession, tenant_ctx
) -> None:
    """Ownership guard: channel rows resolve through the requesting tenant —
    guessing another workspace's integration id is a 404 on BOTH actions."""
    other = Tenant(slug=f"t-{uuid.uuid4().hex[:10]}", name="Other Tenant")
    db.add(other)
    await db.flush()
    await bind_tenant(db, other.id)
    foreign = await _channel_row(db, other.id)
    await bind_tenant(db, tenant_ctx.tenant_id)

    async with AsyncClient(
        transport=ASGITransport(app=_app(db, tenant_ctx)), base_url="http://test"
    ) as client:
        verified = await client.post(f"/api/v1/integrations/{foreign.id}/verify")
        disconnected = await client.post(
            f"/api/v1/integrations/{foreign.id}/disconnect", json={"confirm": True}
        )

    assert verified.status_code == 404
    assert disconnected.status_code == 404
    row = await db.get(Integration, foreign.id)
    assert row.status == "active", "a refused action must not change the foreign row"


async def test_disconnect_requires_explicit_confirmation(db: AsyncSession, tenant_ctx) -> None:
    """The destructive gate: a defaulted body must not cut a live channel."""
    row = await _channel_row(db, tenant_ctx.tenant_id)

    async with AsyncClient(
        transport=ASGITransport(app=_app(db, tenant_ctx)), base_url="http://test"
    ) as client:
        refused = await client.post(f"/api/v1/integrations/{row.id}/disconnect", json={})

    assert refused.status_code == 400, "disconnect without confirm=true is refused"
    assert (await db.get(Integration, row.id)).status == "active"


async def test_disconnect_disables_the_channels_ingress(db: AsyncSession, tenant_ctx) -> None:
    """Checklist 5, second half: after disconnect the channel's tenant-
    resolution key stops matching, so provider deliveries can no longer be
    attributed (and therefore ingested) for this tenant."""
    phone_key = "201009999999"
    row = await _channel_row(db, tenant_ctx.tenant_id, config={"phone_number_id": phone_key})

    def _resolve():
        return db.execute(
            text("SELECT public.resolve_channel_tenant('whatsapp', :k)"),
            {"k": phone_key},
        )

    resolved_before = (await _resolve()).scalar()
    assert str(resolved_before) == str(tenant_ctx.tenant_id), (
        "an active channel must resolve its tenant for ingress"
    )

    async with AsyncClient(
        transport=ASGITransport(app=_app(db, tenant_ctx)), base_url="http://test"
    ) as client:
        disconnected = await client.post(
            f"/api/v1/integrations/{row.id}/disconnect", json={"confirm": True}
        )

    assert disconnected.status_code == 200
    assert disconnected.json()["status"] == "disconnected"
    assert (await _resolve()).scalar() is None, (
        "a disconnected channel must stop resolving — its ingress is dead"
    )
