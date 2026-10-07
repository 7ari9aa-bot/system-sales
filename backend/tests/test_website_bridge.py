"""9.1 close-out — the Website Platform bridge's FIRST dedicated test file.

The bridge is the one surface that talks to an EXTERNAL partner API with a
partner key that must never leak. It had zero tests; this file pins:

1. the error translation: partner outages surface as the unified error
   envelope (status >= 500 → 502 retryable-shaped), 404 degrades to the
   "not provisioned" template offer, and a publish conflict (409) is a
   structured ``ok=False`` result instead of an exception;
2. the identity contract: provision sends the TENANT's identity (external
   tenant id, tenant name, owner email) — never raw credentials;
3. the partner-key hygiene: a missing key fails closed before any network
   call, and the SSO session handler returns only the three fields the
   frontend stores;
4. the catalog projection route: the per-tenant platform key resolves the
   tenant (unknown key → 401, malformed mapping → loud 500), and only
   PUBLISHED products of the key's tenant are served.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.core.errors import ValidationError
from app.modules.catalog import website_platform as bridge
from app.modules.catalog.service import CatalogService
from app.modules.website import client as wp
from app.modules.website import router as website_router


def _ctx(tenant_id: uuid.UUID) -> SimpleNamespace:
    return SimpleNamespace(
        tenant_id=tenant_id,
        user=SimpleNamespace(id=uuid.uuid4()),
        session=None,  # handlers under test monkeypatch the name/email lookups
    )


# --------------------------------- 1. error translation (pure, no DB) -------


async def test_overview_surfaces_a_partner_outage_as_a_502(monkeypatch) -> None:
    async def _down(external_tenant_id: str) -> dict:
        raise wp.WebsitePlatformError(503, "UPSTREAM_DOWN", "partner unreachable")

    monkeypatch.setattr(wp, "resolve_website", _down)
    with pytest.raises(HTTPException) as excinfo:
        await website_router.overview(_ctx(uuid.uuid4()))
    assert excinfo.value.status_code == 502
    assert excinfo.value.detail["code"] == "UPSTREAM_DOWN"


async def test_an_unprovisioned_tenant_is_offered_templates(monkeypatch) -> None:
    async def _missing(external_tenant_id: str) -> dict:
        raise wp.WebsitePlatformError(404, "NOT_FOUND", "no website")

    async def _templates() -> list[dict]:
        return [{"id": "t1", "name": "Starter"}]

    monkeypatch.setattr(wp, "resolve_website", _missing)
    monkeypatch.setattr(wp, "templates", _templates)
    result = await website_router.overview(_ctx(uuid.uuid4()))
    assert result == {"provisioned": False, "templates": [{"id": "t1", "name": "Starter"}]}


async def test_provision_requires_a_template_choice() -> None:
    with pytest.raises(ValidationError):
        await website_router.provision({}, _ctx(uuid.uuid4()))


async def test_provision_sends_the_tenant_identity_not_credentials(monkeypatch) -> None:
    tenant_id = uuid.uuid4()
    captured: dict = {}

    async def _provision(**kwargs) -> dict:
        captured.update(kwargs)
        return {"websiteId": "w-1"}

    async def _resolve(external_tenant_id: str) -> dict:
        return {"websiteId": "w-1", "status": "active"}

    async def _tenant_name(session, tid) -> str:
        return "ACME Co"

    async def _user_email(session, user_id) -> str:
        return "owner@acme.test"

    monkeypatch.setattr(wp, "provision_website", _provision)
    monkeypatch.setattr(wp, "resolve_website", _resolve)
    monkeypatch.setattr(website_router, "_tenant_name", _tenant_name)
    monkeypatch.setattr(website_router, "_user_email", _user_email)

    result = await website_router.provision({"template_id": "t1"}, _ctx(tenant_id))
    assert result["provisioned"] is True
    assert captured["external_tenant_id"] == str(tenant_id)
    assert captured["tenant_name"] == "ACME Co"
    assert captured["email"] == "owner@acme.test"
    assert captured["template_id"] == "t1"


async def test_the_sso_session_returns_exactly_the_studio_contract(monkeypatch) -> None:
    async def _sso(email: str) -> dict:
        return {
            "token": "wp-token",
            "expiresAt": "soon",
            "studioUrl": "https://studio",
            "internal": "x",
        }

    monkeypatch.setattr(wp, "sso_session", _sso)

    async def _user_email(session, user_id) -> str:
        return "owner@acme.test"

    monkeypatch.setattr(website_router, "_user_email", _user_email)
    result = await website_router.session(_ctx(uuid.uuid4()))
    assert set(result) == {"token", "expiresAt", "studioUrl"}
    assert result["token"] == "wp-token"


async def test_a_publish_conflict_is_a_structured_no(monkeypatch) -> None:
    async def _resolve(external_tenant_id: str) -> dict:
        return {"websiteId": "w-1"}

    async def _publish(website_id: str) -> dict:
        raise wp.WebsitePlatformError(409, "PUBLISH_IN_FLIGHT", "already publishing")

    monkeypatch.setattr(wp, "resolve_website", _resolve)
    monkeypatch.setattr(wp, "publish", _publish)
    result = await website_router.publish(_ctx(uuid.uuid4()))
    assert result["ok"] is False
    assert result["code"] == "PUBLISH_IN_FLIGHT"


async def test_a_publish_outage_is_a_502(monkeypatch) -> None:
    async def _resolve(external_tenant_id: str) -> dict:
        return {"websiteId": "w-1"}

    async def _publish(website_id: str) -> dict:
        raise wp.WebsitePlatformError(500, "WP_DOWN", "nope")

    monkeypatch.setattr(wp, "resolve_website", _resolve)
    monkeypatch.setattr(wp, "publish", _publish)
    with pytest.raises(HTTPException) as excinfo:
        await website_router.publish(_ctx(uuid.uuid4()))
    assert excinfo.value.status_code == 502


# --------------------------------- 2. partner-key hygiene -------------------


async def test_a_missing_partner_key_fails_closed_before_any_network(
    monkeypatch,
) -> None:
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "website_platform_api_key", "", raising=False)
    with pytest.raises(wp.WebsitePlatformError) as excinfo:
        await wp._request("GET", "/api/v1/partner/websites?externalUserId=x")
    assert excinfo.value.code == "WP_NOT_CONFIGURED"


# ------------------------------- 3. the catalog projection (DB-backed) ------


async def test_an_unknown_bridge_key_is_unauthorized(monkeypatch) -> None:
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "website_platform_tenant_keys", {}, raising=False)
    with pytest.raises(HTTPException) as excinfo:
        bridge._resolve_tenant_key(x_wp_key="nope")
    assert excinfo.value.status_code == 401


async def test_a_malformed_mapping_is_a_loud_500(monkeypatch) -> None:
    from app.core.config import get_settings

    monkeypatch.setattr(
        get_settings(),
        "website_platform_tenant_keys",
        {"k1": "not-a-uuid"},
        raising=False,
    )
    with pytest.raises(HTTPException) as excinfo:
        bridge._resolve_tenant_key(x_wp_key="k1")
    assert excinfo.value.status_code == 500


async def test_a_valid_key_resolves_its_tenant(monkeypatch) -> None:
    from app.core.config import get_settings

    tenant_id = str(uuid.uuid4())
    monkeypatch.setattr(
        get_settings(),
        "website_platform_tenant_keys",
        {"k1": tenant_id},
        raising=False,
    )
    assert bridge._resolve_tenant_key(x_wp_key="k1") == uuid.UUID(tenant_id)


async def test_the_bridge_serves_only_active_products_of_the_key_tenant(
    db, tenant_ctx, monkeypatch
) -> None:
    from app.core.config import get_settings

    monkeypatch.setattr(
        get_settings(),
        "website_platform_tenant_keys",
        {str(tenant_ctx.tenant_id): "bridge-key"},
        raising=False,
    )
    published = await CatalogService.create_product(
        db, tenant_ctx.tenant_id, title="Live Item", slug=f"live-{uuid.uuid4().hex[:8]}"
    )
    await CatalogService.update_product(db, tenant_ctx.tenant_id, published.id, status="active")
    draft = await CatalogService.create_product(
        db, tenant_ctx.tenant_id, title="Draft Item", slug=f"draft-{uuid.uuid4().hex[:8]}"
    )
    await CatalogService.add_variant(db, tenant_ctx.tenant_id, published.id, price="10.00")

    result = await bridge.website_platform_products(
        key_tenant=tenant_ctx.tenant_id, db=db, limit=100
    )
    ids = {p["id"] for p in result["products"]}
    assert ids == {str(published.id)}
    assert str(draft.id) not in ids
