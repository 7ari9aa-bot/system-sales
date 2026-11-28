"""What the owner's two receipt screens offer must be what the receipt really reads.

The shop profile and the printed-invoice screens are drawn from the settings engine: they list the
settings that are enforced and settable shop-wide. These tests pin the lists the screens ask for
(frontend: ShopProfileForm / PrintAndBarcodeSettings) against the engine and the receipt, so a
setting that stops being enforced, or a receipt key nobody can edit, fails here instead of leaving
an owner with a field that does nothing.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.applications.apparel.modules.pos.receipt_settings import _KEYS as RECEIPT_KEYS
from app.applications.apparel.modules.pos.receipt_settings import receipt_settings
from app.platform.settings.registry import ENFORCED_KEYS, REGISTRY, Scope
from app.platform.settings.service import SettingsService
from tests._pos_helpers import till

SCREENS = Path(__file__).resolve().parents[2] / "frontend/src/applications/apparel/components/settings"


def _keys_in(screen: str, name: str) -> list[str]:
    """The key list a screen file declares, read from the source so the two cannot drift apart."""
    text = (SCREENS / screen).read_text(encoding="utf-8")
    block = re.search(rf"export const {name} = \[(.*?)\];", text, re.S)
    assert block, f"{screen} no longer declares {name}"
    return re.findall(r'"([a-z_.0-9]+)"', block.group(1))


PROFILE = _keys_in("ShopProfileForm.jsx", "SHOP_PROFILE_KEYS")
PRINT = _keys_in("PrintAndBarcodeSettings.jsx", "PRINT_KEYS")


@pytest.mark.parametrize("key", [*PROFILE, *PRINT])
def test_every_field_an_owner_is_offered_is_real_enforced_and_settable_shop_wide(key: str) -> None:
    assert key in REGISTRY, f"{key} is not a setting"
    assert key in ENFORCED_KEYS, f"{key} is offered but nothing reads it"
    assert Scope.TENANT in REGISTRY[key].scopes, f"{key} cannot be set for the whole shop"


@pytest.mark.parametrize("key", [*PROFILE, *PRINT])
def test_every_field_an_owner_is_offered_reaches_the_receipt(key: str) -> None:
    """Offering a field that the receipt never reads would be a switch wired to nothing."""
    assert key in RECEIPT_KEYS, f"{key} is on the screen but the receipt does not read it"


def test_the_industry_choice_is_not_on_the_shop_profile() -> None:
    """It changes which capabilities are on, so it is not edited among the shop details."""
    assert "business.vertical" not in PROFILE


POS_PAGE = Path(__file__).resolve().parents[2] / "frontend/src/pages/settings/PosSettings.jsx"


def _policy_tab_offers_the_whole_pos_domain() -> set[str]:
    """The keys the shop-policy tab can edit: it renders the engine's whole ``pos`` domain.

    The tab is ``<ShopPolicySettings />`` with no ``keys`` prop, and the component reads that as
    "every enforced setting of the domain" — so a pos key is offered there without any file
    naming it. That is how the return and exchange windows are editable even though no screen
    lists them, and it is why this check has to read the tab rather than a key array.
    """
    text = POS_PAGE.read_text(encoding="utf-8")
    assert re.search(r"render:\s*\(\)\s*=>\s*<ShopPolicySettings\s*/>", text), (
        "the shop-policy tab no longer renders the whole pos domain"
    )
    return {key for key in ENFORCED_KEYS if REGISTRY[key].domain == "pos"}


def test_no_receipt_setting_is_missing_from_the_screens() -> None:
    """A key the receipt reads must be editable somewhere."""
    offered = set(PROFILE) | set(PRINT) | _policy_tab_offers_the_whole_pos_domain()
    missing = set(RECEIPT_KEYS) - offered
    assert not missing, f"the receipt reads {sorted(missing)} but no screen offers them"


@pytest.mark.asyncio
async def test_what_the_screen_saves_is_what_the_receipt_prints(db, tenant_ctx) -> None:
    """Save the way the screen does (shop-wide, one bulk write), then read the receipt."""
    shift, _variant, _customer = await till(db, tenant_ctx)
    await SettingsService(db, tenant_ctx.tenant_id).bulk_set(
        {
            "business.trade_name": "محل النور",
            "business.address.line1": "٥ شارع التحرير",
            "business.address.city": "الجيزة",
            "business.phone": "0122",
            "business.tax_id": "999-111",
            "print.paper_width": "58mm",
            "print.copies": 2,
            "print.show_logo": True,
            "print.header_text": "أهلاً بيك",
            "print.footer_text": "شكراً لزيارتكم",
            "print.show_tax_detail": True,
        },
        scope=Scope.TENANT,
    )
    shop = await receipt_settings(db, tenant_ctx.tenant_id, register_id=shift.register_id)
    assert shop["shop_name"] == "محل النور"
    assert shop["address"] == "٥ شارع التحرير, الجيزة"
    assert shop["phone"] == "0122"
    assert shop["tax_id"] == "999-111"
    assert shop["paper_mm"] == 58
    assert shop["copies"] == 2
    assert shop["show_logo"] is True
    assert shop["header_text"] == "أهلاً بيك"
    assert shop["footer_text"] == "شكراً لزيارتكم"
    assert shop["show_tax_detail"] is True
