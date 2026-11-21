"""One account, several activities: each workspace has its own vertical and capabilities.

A distribution company that also runs a clothes shop is one account with two workspaces. The
vertical and the capability switches are settings, so they may be set per workspace; a workspace
that sets nothing keeps the account's answer, and a request in no workspace reads the account's own
values exactly as before workspaces had settings.
"""

from __future__ import annotations

import uuid

import pytest

from app.core.tenancy import reset_current_scope, set_current_scope
from app.modules.identity.models import Location, Workspace
from app.modules.settings.capabilities import shop_capabilities
from app.modules.settings.scope_graph import UnknownScopeError
from app.modules.settings.service import SettingsService

pytestmark = pytest.mark.asyncio


async def _workspace(db, tenant_id, slug: str) -> Workspace:
    ws = Workspace(tenant_id=tenant_id, name=slug, slug=f"{slug}-{uuid.uuid4().hex[:6]}")
    db.add(ws)
    await db.flush()
    return ws


async def test_a_workspace_value_wins_in_that_workspace_and_not_in_its_sibling(
    db, tenant_ctx
) -> None:
    tid = tenant_ctx.tenant_id
    shop = await _workspace(db, tid, "shop")
    depot = await _workspace(db, tid, "depot")
    s = SettingsService(db, tid)
    await s.set("business.vertical", "apparel", scope="workspace", scope_id=shop.id)
    await s.set("business.vertical", "pharmacy", scope="workspace", scope_id=depot.id)

    in_shop = await shop_capabilities(db, tid, workspace_id=shop.id)
    in_depot = await shop_capabilities(db, tid, workspace_id=depot.id)

    assert in_shop["vertical"] == "apparel"
    assert in_shop["capabilities"]["variant_matrix"] is True
    assert in_shop["capabilities"]["lot_expiry"] is False
    assert in_depot["vertical"] == "pharmacy"
    assert in_depot["capabilities"]["lot_expiry"] is True
    assert in_depot["capabilities"]["variant_matrix"] is False


async def test_a_workspace_that_sets_nothing_keeps_the_accounts_answer(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    other = await _workspace(db, tid, "other")
    await SettingsService(db, tid).set("business.vertical", "apparel")  # the account's own

    out = await shop_capabilities(db, tid, workspace_id=other.id)

    assert out["vertical"] == "apparel"
    assert out["capabilities"]["variant_matrix"] is True


async def test_a_workspace_setting_does_not_leak_into_the_account_or_a_request_in_none(
    db, tenant_ctx
) -> None:
    tid = tenant_ctx.tenant_id
    shop = await _workspace(db, tid, "shop")
    await SettingsService(db, tid).set(
        "business.vertical", "pharmacy", scope="workspace", scope_id=shop.id
    )

    assert (await shop_capabilities(db, tid))["vertical"] == "general"  # no workspace in scope


async def test_a_capability_switch_can_be_set_for_one_workspace_only(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    shop = await _workspace(db, tid, "shop")
    other = await _workspace(db, tid, "other")
    await SettingsService(db, tid).set(
        "capability.fefo_picking", True, scope="workspace", scope_id=shop.id
    )

    assert (await shop_capabilities(db, tid, workspace_id=shop.id))["capabilities"][
        "fefo_picking"
    ] is True
    assert (await shop_capabilities(db, tid, workspace_id=other.id))["capabilities"][
        "fefo_picking"
    ] is False


async def test_the_request_workspace_is_used_when_none_is_named(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    shop = await _workspace(db, tid, "shop")
    await SettingsService(db, tid).set(
        "business.vertical", "pharmacy", scope="workspace", scope_id=shop.id
    )

    token = set_current_scope(shop.id, None)
    try:
        inside = await shop_capabilities(db, tid)
    finally:
        reset_current_scope(token)

    assert inside["vertical"] == "pharmacy"
    assert (await shop_capabilities(db, tid))["vertical"] == "general"


async def test_a_branch_inherits_its_workspaces_value_then_the_accounts(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    shop = await _workspace(db, tid, "shop")
    branch = Location(tenant_id=tid, workspace_id=shop.id, name="Main", code="M1")
    db.add(branch)
    await db.flush()
    s = SettingsService(db, tid)
    await s.set("business.vertical", "apparel", scope="workspace", scope_id=shop.id)

    got = await s.resolve("business.vertical", scope="branch", scope_id=branch.id)

    assert got.value == "apparel"
    assert got.scope == "workspace"
    assert got.is_inherited is True


async def test_a_branch_value_still_beats_its_workspace(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    shop = await _workspace(db, tid, "shop")
    branch = Location(tenant_id=tid, workspace_id=shop.id, name="Main", code="M2")
    db.add(branch)
    await db.flush()
    s = SettingsService(db, tid)
    await s.set("business.phone", "02-111")
    await s.set("business.phone", "02-999", scope="branch", scope_id=branch.id)

    got = await s.resolve("business.phone", scope="branch", scope_id=branch.id)

    assert got.value == "02-999"
    assert got.scope == "branch"


async def test_a_workspace_that_is_not_the_accounts_is_refused(db, tenant_ctx) -> None:
    tid = tenant_ctx.tenant_id
    with pytest.raises(UnknownScopeError):
        await SettingsService(db, tid).set(
            "business.vertical", "apparel", scope="workspace", scope_id=uuid.uuid4()
        )


async def test_a_workspace_of_another_account_cannot_be_written_or_read(
    db, tenant_ctx, _engine
) -> None:
    from tests._pos_helpers import in_tx, make_tenant

    url = str(_engine.url.render_as_string(hide_password=False))
    engine, factory, stranger_tid, _ = await make_tenant(url, "stranger")
    try:

        async def _make(s):
            ws = Workspace(tenant_id=stranger_tid, name="theirs", slug=f"t-{uuid.uuid4().hex[:6]}")
            s.add(ws)
            await s.flush()
            return ws.id

        theirs = await in_tx(factory, stranger_tid, _make)
        assert isinstance(theirs, uuid.UUID)

        with pytest.raises(UnknownScopeError):
            await SettingsService(db, tenant_ctx.tenant_id).set(
                "business.vertical", "apparel", scope="workspace", scope_id=theirs
            )
        # reading with their id from our account falls back to our own answer, never theirs
        out = await shop_capabilities(db, tenant_ctx.tenant_id, workspace_id=theirs)
        assert out["vertical"] == "general"
    finally:
        await engine.dispose()


async def test_a_workspace_that_vanished_falls_back_instead_of_failing_the_sale(
    db, tenant_ctx
) -> None:
    tid = tenant_ctx.tenant_id
    await SettingsService(db, tid).set("business.vertical", "apparel")

    out = await shop_capabilities(db, tid, workspace_id=uuid.uuid4())

    assert out["vertical"] == "apparel"


async def test_only_the_vertical_and_capabilities_open_a_workspace_level(db, tenant_ctx) -> None:
    """Opening a scope is per key: a shop's tax id is the account's, never one workspace's."""
    tid = tenant_ctx.tenant_id
    shop = await _workspace(db, tid, "shop")
    with pytest.raises(Exception) as excinfo:
        await SettingsService(db, tid).set(
            "business.tax_id", "123", scope="workspace", scope_id=shop.id
        )
    assert "scope" in str(excinfo.value).lower()
