"""The channel sync path end to end: Shopify payload → a real catalog row.

This is the half the gap register could not have caught: the adapter's call
target existed nowhere, so a sync reported nothing while writing nothing. These
run the production ``CatalogService.upsert_from_external`` against the
transactional test schema, with Shopify itself behind ``httpx.MockTransport``
(no network, no credentials).

DB-backed: they SKIP locally without ``DATABASE_URL_APP_ADMIN`` and run in CI.
The pure mirror of these rules — refusals, currency resolution, report
accounting — is in ``tests/test_shopify_adapter.py``.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.external.source_of_truth import SourceOfTruthService
from app.modules.catalog.models import Product, ProductVariant
from app.modules.catalog.service import CatalogService
from app.modules.errors import ConflictError
from tests.test_shopify_adapter import _adapter, _product


async def _external_products_channel(db: AsyncSession, tenant_id: uuid.UUID) -> None:
    """§161: nothing syncs until the tenant says the store owns its products."""
    await SourceOfTruthService.upsert_policy(
        db,
        tenant_id,
        provider="shopify",
        entity_type="product",
        source_mode="external",
        sync_direction="inbound",
    )
    await db.flush()


async def _reset_version_gate(db: AsyncSession, tenant_id: uuid.UUID) -> None:
    """Clear the incremental marker: this run is a full re-sync, not a poll."""
    policy = await SourceOfTruthService.get_policy(
        db, tenant_id, provider="shopify", entity_type="product"
    )
    policy.external_version = None
    await db.flush()


async def _rows(db: AsyncSession, tenant_id: uuid.UUID) -> list[Product]:
    """Every product this tenant has — the sync may not leave a second one."""
    return list(
        (await db.execute(select(Product).where(Product.tenant_id == tenant_id))).scalars().all()
    )


async def test_sync_products_writes_a_real_product_and_variant(
    db: AsyncSession, tenant_ctx
) -> None:
    tenant_id = tenant_ctx.tenant_id
    await _external_products_channel(db, tenant_id)
    adapter, _seen = _adapter(products=[_product(price="19.99")], shop_currency="EGP")

    report = await adapter.sync_products(db, tenant_id)

    assert report["synced"] == 1 and report["errors"] == 0 and report["conflicts"] == 0
    products = await _rows(db, tenant_id)
    assert len(products) == 1
    product = products[0]
    assert product.slug == "koshari-bowl"
    assert product.status == "active"
    # provenance, so the next sync recognises its own row instead of cloning it
    assert product.attributes["_source"] == "shopify"
    assert product.attributes["_external_id"] == "111"

    variants = await CatalogService.list_variants(db, tenant_id, product.id)
    assert len(variants) == 1
    assert variants[0].sku == "KB-111"
    assert variants[0].price == Decimal("19.99")


async def test_resync_updates_the_row_it_already_owns(db: AsyncSession, tenant_ctx) -> None:
    tenant_id = tenant_ctx.tenant_id
    await _external_products_channel(db, tenant_id)
    first, _seen = _adapter(products=[_product(price="19.99")], shop_currency="EGP")
    await first.sync_products(db, tenant_id)

    await _reset_version_gate(db, tenant_id)
    renamed = _product(price="17.50")
    renamed["title"] = "Koshari Bowl, large"
    second, _seen2 = _adapter(products=[renamed], shop_currency="EGP")
    report = await second.sync_products(db, tenant_id)

    assert report["synced"] == 1 and report["errors"] == 0
    products = await _rows(db, tenant_id)
    assert len(products) == 1, "a re-sync must update, not duplicate"
    assert products[0].title == "Koshari Bowl, large"
    variants = list(
        (await db.execute(select(ProductVariant).where(ProductVariant.tenant_id == tenant_id)))
        .scalars()
        .all()
    )
    assert len(variants) == 1
    assert variants[0].price == Decimal("17.50")


async def test_a_foreign_currency_price_lands_nothing(db: AsyncSession, tenant_ctx) -> None:
    """Refusal at the boundary: a tenant's money is one currency (§47)."""
    tenant_id = tenant_ctx.tenant_id
    await _external_products_channel(db, tenant_id)
    adapter, _seen = _adapter(products=[_product(currency="USD")], shop_currency="USD")

    report = await adapter.sync_products(db, tenant_id)

    assert report["conflicts"] == 1 and report["synced"] == 0
    assert await _rows(db, tenant_id) == []


async def test_upsert_from_external_refuses_a_foreign_currency(
    db: AsyncSession, tenant_ctx
) -> None:
    """The owning service — not only the adapter — gates the currency."""
    tenant_id = tenant_ctx.tenant_id

    with pytest.raises(ConflictError):
        await CatalogService.upsert_from_external(
            db,
            tenant_id,
            external_ref="111",
            data={"title": "Koshari Bowl", "slug": "koshari-bowl"},
            source="shopify",
            currency="USD",
        )
    await db.flush()

    counted = (
        await db.execute(
            select(func.count()).select_from(Product).where(Product.tenant_id == tenant_id)
        )
    ).scalar_one()
    assert counted == 0


async def test_upsert_from_external_writes_in_the_tenants_currency(
    db: AsyncSession, tenant_ctx
) -> None:
    """With no currency argument the tenant's own row answers."""
    tenant_id = tenant_ctx.tenant_id

    product = await CatalogService.upsert_from_external(
        db,
        tenant_id,
        external_ref="111",
        data={
            "title": "Koshari Bowl",
            "slug": "koshari-bowl",
            "variants": [{"title": "Default", "price": "25.00", "sku": "KB-111"}],
        },
        source="shopify",
    )
    await db.flush()

    variants = await CatalogService.list_variants(db, tenant_id, product.id)
    assert variants[0].price == Decimal("25.00")


# --------------------------------------------------------------------------
# Package 5.1 — checklist 4: CHANNEL ACCOUNT STATE SYNC (not catalog sync —
# that half lives above). The verify surface is the only writer of channel
# state besides connect/disconnect: a failed recheck must DEMOTE the channel
# to reauth_required (never silently keep it active), leave the stored
# credentials untouched, expose no credential material, and leave an audit
# row. A successful recheck re-arms the channel under the same rules.
# --------------------------------------------------------------------------

from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import text as sa_text  # noqa: E402

from app.core.errors import ValidationError as DomainValidationError  # noqa: E402
from app.core.secrets import decrypt_credentials_dict, encrypt_credentials_dict  # noqa: E402
from app.main import create_app  # noqa: E402
from app.modules.identity.deps import (  # noqa: E402
    AuthedUser,
    TenantContext,
    get_tenant_ctx,
)
from app.modules.platform.integration_verifier import VerifiedChannel  # noqa: E402
from app.modules.platform.models import AuditLog, Integration  # noqa: E402


def _sync_app(db: AsyncSession, tenant_ctx) -> object:
    """The real app with the tenant dependency replaced by the bound ctx.

    Route, lifecycle table, audit writer and error handlers are all the
    production ones; only the provider HTTP seam is patched per test.
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


async def _active_channel(db: AsyncSession, tenant_id: uuid.UUID) -> Integration:
    row = Integration(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        provider="whatsapp",
        kind="channel",
        status="active",
        config={"phone_number_id": "201008888888"},
        credentials=encrypt_credentials_dict({"access_token": "live-provider-secret"}),
    )
    db.add(row)
    await db.flush()
    return row


async def test_failed_recheck_demotes_to_reauth_required_and_audits(
    db: AsyncSession, tenant_ctx, monkeypatch
) -> None:
    row = await _active_channel(db, tenant_ctx.tenant_id)

    async def reject(_provider, _credentials, _config, *, client=None):
        raise DomainValidationError("The provider rejected these credentials.")

    monkeypatch.setattr("app.modules.customers.router.verify_channel_credentials", reject)

    async with AsyncClient(
        transport=ASGITransport(app=_sync_app(db, tenant_ctx)), base_url="http://test"
    ) as client:
        response = await client.post(f"/api/v1/integrations/{row.id}/verify")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "reauth_required", "a dead credential must demote"
    assert body["credentials_verified"] is False
    assert "live-provider-secret" not in response.text, "no credential material"

    await db.refresh(row)
    assert row.status == "reauth_required"
    assert decrypt_credentials_dict(row.credentials) == {"access_token": "live-provider-secret"}, (
        "a state sync must not rewrite credentials"
    )

    audit = (
        await db.execute(
            select(AuditLog).where(
                AuditLog.tenant_id == tenant_ctx.tenant_id,
                AuditLog.action == "integration.verification_failed",
                AuditLog.resource_id == str(row.id),
            )
        )
    ).scalar_one()
    assert audit.before == {"status": "active"}
    assert audit.after["status"] == "reauth_required"


async def test_successful_recheck_rearms_the_channel_without_credential_writes(
    db: AsyncSession, tenant_ctx, monkeypatch
) -> None:
    row = await _active_channel(db, tenant_ctx.tenant_id)

    async def approve(provider, credentials, config, *, client=None):
        assert credentials == {"access_token": "live-provider-secret"}
        return VerifiedChannel({"phone_number_id": "201008888888"}, "Shop")

    monkeypatch.setattr("app.modules.customers.router.verify_channel_credentials", approve)

    async with AsyncClient(
        transport=ASGITransport(app=_sync_app(db, tenant_ctx)), base_url="http://test"
    ) as client:
        response = await client.post(f"/api/v1/integrations/{row.id}/verify")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "active"
    assert body["credentials_verified"] is True
    assert "live-provider-secret" not in response.text

    await db.refresh(row)
    assert row.status == "active"
    assert decrypt_credentials_dict(row.credentials) == {"access_token": "live-provider-secret"}, (
        "a re-verification must not rewrite the stored credential"
    )
    assert row.config["_connection"]["verified_at"]

    audit = (
        await db.execute(
            select(AuditLog).where(
                AuditLog.tenant_id == tenant_ctx.tenant_id,
                AuditLog.action == "integration.reverified",
                AuditLog.resource_id == str(row.id),
            )
        )
    ).scalar_one()
    assert audit.after["status"] == "active"


async def test_channel_state_only_resolves_traffic_while_active(
    db: AsyncSession, tenant_ctx
) -> None:
    """The state → ingress contract at the resolver: reauth_required and
    disabled states never route provider traffic, only active/connected do."""
    key = "201007777777"
    row = Integration(
        id=uuid.uuid4(),
        tenant_id=tenant_ctx.tenant_id,
        provider="whatsapp",
        kind="channel",
        status="reauth_required",
        config={"phone_number_id": key},
        credentials=encrypt_credentials_dict({"access_token": "s"}),
    )
    db.add(row)
    await db.flush()

    def _resolve():
        return db.execute(
            sa_text("SELECT public.resolve_channel_tenant('whatsapp', :k)"), {"k": key}
        )

    assert (await _resolve()).scalar() is None, "reauth_required must not receive provider traffic"
    row.status = "active"
    await db.flush()
    assert str((await _resolve()).scalar()) == str(tenant_ctx.tenant_id)
    row.status = "disabled"
    await db.flush()
    assert (await _resolve()).scalar() is None
