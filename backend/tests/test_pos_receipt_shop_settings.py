"""The receipt says what the shop owner decided, not what the code once assumed.

Wording, paper width, copies and the exchange period are the shop's own policy. These tests change
the setting and read the receipt back: a shop that gives 30 days prints 30, a branch prints its own
footer, a bad value never stops a receipt from printing.
"""

from __future__ import annotations

import pytest

from app.modules.pos.receipt_settings import receipt_settings
from app.modules.pos.service import PosService
from app.modules.settings.service import SettingsService
from tests._pos_helpers import till

pytestmark = pytest.mark.asyncio


async def _receipt(db, tenant_ctx):
    shift, variant, customer = await till(db, tenant_ctx)
    out = await PosService.record_sale(
        db,
        tenant_ctx.tenant_id,
        shift.register_id,
        items=[{"variant_id": str(variant.id), "quantity": 1}],
        customer_id=customer.id,
        actor_user_id=tenant_ctx.user.id,
    )
    return shift, out


async def _shop_block(db, tenant_ctx, shift):
    return await receipt_settings(db, tenant_ctx.tenant_id, register_id=shift.register_id)


async def test_an_unconfigured_shop_gets_plain_defaults(db, tenant_ctx) -> None:
    shift, _ = await _receipt(db, tenant_ctx)
    shop = await _shop_block(db, tenant_ctx, shift)
    assert shop["shop_name"] is None
    assert shop["address"] is None and shop["phone"] is None and shop["tax_id"] is None
    assert shop["paper_mm"] == 80
    assert shop["copies"] == 1
    assert shop["header_text"] is None and shop["footer_text"] is None
    # Exchange is off until the owner turns it on: the receipt must not promise it.
    assert shop["exchange_days"] == 0


async def test_the_receipt_prints_the_exchange_period_the_owner_set(db, tenant_ctx) -> None:
    shift, _ = await _receipt(db, tenant_ctx)
    await SettingsService(db, tenant_ctx.tenant_id).set("pos.exchange_max_days", 30)
    assert (await _shop_block(db, tenant_ctx, shift))["exchange_days"] == 30
    await SettingsService(db, tenant_ctx.tenant_id).set("pos.exchange_max_days", 7)
    assert (await _shop_block(db, tenant_ctx, shift))["exchange_days"] == 7


async def test_shop_identity_comes_from_the_owners_settings(db, tenant_ctx) -> None:
    shift, _ = await _receipt(db, tenant_ctx)
    s = SettingsService(db, tenant_ctx.tenant_id)
    await s.set("business.trade_name", "  محل الأمل  ")
    await s.set("business.address.line1", "١٢ شارع النيل")
    await s.set("business.address.city", "القاهرة")
    await s.set("business.phone", "0100")
    await s.set("business.tax_id", "123-456")
    shop = await _shop_block(db, tenant_ctx, shift)
    assert shop["shop_name"] == "محل الأمل"
    assert shop["address"] == "١٢ شارع النيل, القاهرة"
    assert shop["phone"] == "0100"
    assert shop["tax_id"] == "123-456"


async def test_the_trade_name_wins_over_the_legal_name_and_either_alone_is_used(
    db, tenant_ctx
) -> None:
    shift, _ = await _receipt(db, tenant_ctx)
    s = SettingsService(db, tenant_ctx.tenant_id)
    await s.set("business.legal_name", "الأمل للتجارة ش.م.م")
    assert (await _shop_block(db, tenant_ctx, shift))["shop_name"] == "الأمل للتجارة ش.م.م"
    await s.set("business.trade_name", "الأمل")
    assert (await _shop_block(db, tenant_ctx, shift))["shop_name"] == "الأمل"


async def test_a_city_alone_is_the_address_without_a_dangling_comma(db, tenant_ctx) -> None:
    shift, _ = await _receipt(db, tenant_ctx)
    await SettingsService(db, tenant_ctx.tenant_id).set("business.address.city", "الإسكندرية")
    assert (await _shop_block(db, tenant_ctx, shift))["address"] == "الإسكندرية"


@pytest.mark.parametrize(("setting", "mm"), [("58mm", 58), ("80mm", 80), ("a4", 80)])
async def test_paper_width_maps_to_the_roll_the_printer_takes(db, tenant_ctx, setting, mm) -> None:
    shift, _ = await _receipt(db, tenant_ctx)
    await SettingsService(db, tenant_ctx.tenant_id).set("print.paper_width", setting)
    assert (await _shop_block(db, tenant_ctx, shift))["paper_mm"] == mm


async def test_header_footer_copies_and_switches_follow_the_owner(db, tenant_ctx) -> None:
    shift, _ = await _receipt(db, tenant_ctx)
    s = SettingsService(db, tenant_ctx.tenant_id)
    await s.set("print.header_text", " أهلاً بكم ")
    await s.set("print.footer_text", "الإرجاع بالفاتورة فقط")
    await s.set("print.copies", 2)
    await s.set("print.show_logo", False)
    await s.set("print.show_tax_detail", False)
    shop = await _shop_block(db, tenant_ctx, shift)
    assert shop["header_text"] == "أهلاً بكم"
    assert shop["footer_text"] == "الإرجاع بالفاتورة فقط"
    assert shop["copies"] == 2
    assert shop["show_logo"] is False
    assert shop["show_tax_detail"] is False


async def test_a_blank_footer_is_absent_not_an_empty_line(db, tenant_ctx) -> None:
    shift, _ = await _receipt(db, tenant_ctx)
    await SettingsService(db, tenant_ctx.tenant_id).set("print.footer_text", "   ")
    assert (await _shop_block(db, tenant_ctx, shift))["footer_text"] is None


async def test_the_receipt_read_model_carries_the_shop_block(db, tenant_ctx) -> None:
    shift, out = await _receipt(db, tenant_ctx)
    await SettingsService(db, tenant_ctx.tenant_id).set("pos.exchange_max_days", 21)
    receipt = await PosService.get_receipt(db, tenant_ctx.tenant_id, out["receipt_id"])
    assert receipt["shop"]["exchange_days"] == 21
    assert receipt["shop"]["paper_mm"] == 80


async def test_a_till_can_print_its_own_paper_while_the_shop_uses_another(db, tenant_ctx) -> None:
    shift, _ = await _receipt(db, tenant_ctx)
    s = SettingsService(db, tenant_ctx.tenant_id)
    await s.set("print.paper_width", "80mm")
    await s.set("print.paper_width", "58mm", scope="register", scope_id=shift.register_id)
    assert (await _shop_block(db, tenant_ctx, shift))["paper_mm"] == 58
    # A receipt that knows no till reads the shop-wide value.
    shop_wide = await receipt_settings(db, tenant_ctx.tenant_id, register_id=None)
    assert shop_wide["paper_mm"] == 80


async def test_the_receipt_is_read_at_the_till_it_was_issued_on(db, tenant_ctx) -> None:
    shift, out = await _receipt(db, tenant_ctx)
    s = SettingsService(db, tenant_ctx.tenant_id)
    await s.set("print.copies", 1)
    await s.set("print.copies", 3, scope="register", scope_id=shift.register_id)
    receipt = await PosService.get_receipt(db, tenant_ctx.tenant_id, out["receipt_id"])
    assert receipt["shop"]["copies"] == 3


def test_a_value_the_settings_would_refuse_still_prints_with_a_safe_fallback() -> None:
    from app.modules.pos import receipt_settings as rs

    assert rs._whole("x", default=7, low=0, high=9) == 7
    assert rs._whole(True, default=7, low=0, high=9) == 7
    assert rs._whole(float("nan"), default=7, low=0, high=9) == 7
    assert rs._whole(float("inf"), default=7, low=0, high=9) == 7
    assert rs._whole(None, default=7, low=0, high=9) == 7
    assert rs._whole(-4, default=7, low=0, high=9) == 0
    assert rs._whole(99, default=7, low=0, high=9) == 9
    assert rs._whole(2.9, default=7, low=0, high=9) == 2


async def test_a_stored_value_the_settings_no_longer_allow_still_prints(
    db, tenant_ctx, monkeypatch
) -> None:
    """A row written before a rule was tightened must not stop a sale from printing."""
    from types import SimpleNamespace

    shift, _ = await _receipt(db, tenant_ctx)
    real = SettingsService.resolve_many

    async def corrupt(self, keys, **kw):
        out = await real(self, keys, **kw)
        bad = {
            "print.paper_width": "46mm",
            "pos.exchange_max_days": "soon",
            "print.copies": None,
            "print.show_logo": "yes",
            "business.trade_name": 7,
        }
        return {k: SimpleNamespace(value=bad.get(k, r.value)) for k, r in out.items()}

    monkeypatch.setattr(SettingsService, "resolve_many", corrupt)
    shop = await _shop_block(db, tenant_ctx, shift)
    assert shop["paper_mm"] == 80
    assert shop["exchange_days"] == 0
    assert shop["copies"] == 1
    assert shop["show_logo"] is False
    assert shop["shop_name"] is None

async def test_the_whole_legal_identity_is_readable_from_the_settings(db, tenant_ctx) -> None:
    """A tax invoice needs more than a name: register number, postal code, email, website.

    These four used to be saved-able in the registry but read by nobody, so the owner could type
    them and nothing ever printed them. They now come back with the rest of the shop block.
    """
    shift, _ = await _receipt(db, tenant_ctx)
    s = SettingsService(db, tenant_ctx.tenant_id)
    await s.set("business.commercial_register", "CR-99887")
    await s.set("business.email", "shop@example.com")
    await s.set("business.website", "https://example.com")
    await s.set("business.address.postal_code", "11511")
    shop = await _shop_block(db, tenant_ctx, shift)
    assert shop["commercial_register"] == "CR-99887"
    assert shop["email"] == "shop@example.com"
    assert shop["website"] == "https://example.com"
    assert shop["postal_code"] == "11511"


async def test_an_empty_identity_field_prints_nothing(db, tenant_ctx) -> None:
    shift, _ = await _receipt(db, tenant_ctx)
    await SettingsService(db, tenant_ctx.tenant_id).set("business.commercial_register", "   ")
    shop = await _shop_block(db, tenant_ctx, shift)
    assert shop["commercial_register"] is None
    assert shop["email"] is None and shop["website"] is None and shop["postal_code"] is None
