"""The shop's capabilities as the owner has set them, read back from the database."""

from __future__ import annotations

import pytest

from app.modules.settings.capabilities import shop_capabilities
from app.modules.settings.service import SettingsService

pytestmark = pytest.mark.asyncio


async def test_a_new_shop_is_the_plain_shop(db, tenant_ctx) -> None:
    out = await shop_capabilities(db, tenant_ctx.tenant_id)
    assert out["vertical"] == "general"
    assert not any(out["capabilities"].values())


async def test_choosing_a_vertical_switches_on_its_capabilities(db, tenant_ctx) -> None:
    s = SettingsService(db, tenant_ctx.tenant_id)
    await s.set("business.vertical", "pharmacy")
    out = await shop_capabilities(db, tenant_ctx.tenant_id)
    assert out["vertical"] == "pharmacy"
    assert out["capabilities"]["lot_expiry"] is True
    assert out["capabilities"]["prescription_required"] is True
    assert out["capabilities"]["variant_matrix"] is False


async def test_the_owner_can_switch_one_capability_either_way(db, tenant_ctx) -> None:
    s = SettingsService(db, tenant_ctx.tenant_id)
    await s.set("business.vertical", "pharmacy")
    await s.set("capability.lot_expiry", False)  # off although the vertical starts it on
    await s.set("capability.variant_matrix", True)  # on although the vertical starts it off
    caps = (await shop_capabilities(db, tenant_ctx.tenant_id))["capabilities"]
    assert caps["lot_expiry"] is False
    assert caps["variant_matrix"] is True
    assert caps["fefo_picking"] is True  # untouched ones keep the vertical's answer


async def test_changing_the_vertical_later_keeps_what_the_owner_chose(db, tenant_ctx) -> None:
    s = SettingsService(db, tenant_ctx.tenant_id)
    await s.set("capability.weight_scale", True)
    await s.set("business.vertical", "restaurant")
    caps = (await shop_capabilities(db, tenant_ctx.tenant_id))["capabilities"]
    assert caps["weight_scale"] is True
    assert caps["modifiers"] is True
