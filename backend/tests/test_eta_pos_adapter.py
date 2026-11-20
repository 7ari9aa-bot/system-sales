"""A real till sale / return becomes an ETA receipt whose numbers equal what the customer paid.

The till records goods and a net value per line, and nothing about VAT, payment or item codes.
These tests pin what the converter makes of that, and every reason it refuses to guess.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import sqlalchemy as sa

import app.core.model_registry  # noqa: F401
from app.core.errors import ValidationError
from app.modules.catalog.service import CatalogService
from app.modules.einvoice.pos_adapter import NotReady, build_context, eta_settings, split_line
from app.modules.einvoice.providers.eta.calc import q5
from app.modules.pos.models import PosReceipt
from app.modules.pos.service import PosService
from app.modules.settings.service import SettingsService
from tests._pos_sell import sell as pos_sell
from tests.test_pos_returns import _customer, _register, _sellable_variant

pytestmark = pytest.mark.asyncio


async def _configure(db, tid, **settings):
    svc = SettingsService(db, tid)
    base = {"business.tax_id": "674859545", "business.legal_name": "متجر الملابس"}
    for key, value in {**base, **settings}.items():
        await svc.set(key, value)


async def _coded(db, tid, variant, code="EG-1001", kind="egs"):
    await CatalogService.add_identifier(db, tid, variant.id, kind, code)


async def _sold(db, tenant_ctx, *, price="114.00", qty=2, pct=None, coded=True):
    tid = tenant_ctx.tenant_id
    register = await _register(db, tenant_ctx)
    shift = await PosService.open_session(db, tid, register.id)
    variant = await _sellable_variant(db, tenant_ctx, price=price, stock=50)
    if coded:
        await _coded(db, tid, variant)
    customer = await _customer(db, tenant_ctx)
    item = {"variant_id": str(variant.id), "quantity": qty}
    if pct is not None:
        item["discount_pct"] = pct
    sold = await pos_sell(db, tid, shift.id, customer_id=customer.id, items=[item])
    receipt = (
        await db.execute(sa.select(PosReceipt).where(PosReceipt.id == sold["receipt_id"]))
    ).scalar_one()
    return shift, variant, sold, receipt


class TestSplitLine:
    def test_a_vat_inclusive_shelf_price_is_backed_out_not_added_on(self):
        unit, disc = split_line(
            Decimal("228"), 2, Decimal("114"), includes_vat=True, rate=Decimal("14")
        )
        assert unit == Decimal("100.00000") and disc == Decimal("0.00000")

    def test_a_till_discount_becomes_a_discount_before_vat(self):
        # 2 x 114 less 10% = 205.20 paid; before VAT that is 180, so 20 of discount on 200
        unit, disc = split_line(
            Decimal("205.20"), 2, Decimal("114"), includes_vat=True, rate=Decimal("14")
        )
        assert unit == Decimal("100.00000") and disc == Decimal("20.00000")

    def test_vat_exclusive_prices_are_kept_as_they_are(self):
        unit, disc = split_line(
            Decimal("200"), 2, Decimal("100"), includes_vat=False, rate=Decimal("14")
        )
        assert unit == Decimal("100.00000") and disc == Decimal("0.00000")

    def test_the_discount_is_never_negative(self):
        _, disc = split_line(
            Decimal("300"), 2, Decimal("100"), includes_vat=False, rate=Decimal("14")
        )
        assert disc == Decimal(0)

    def test_the_receipt_total_equals_what_was_paid_for_any_price_quantity_and_discount(self):
        import random

        rng = random.Random(11)
        for _ in range(3000):
            qty = rng.randint(1, 9)
            gross = Decimal(rng.randint(100, 500000)) / 100
            pct = Decimal(rng.choice([0, 0, 5, 10, 12.5, 20, 33.33]))
            paid = (gross * qty * (1 - pct / 100)).quantize(Decimal("0.01"))
            for incl in (True, False):
                unit, disc = split_line(paid, qty, gross, includes_vat=incl, rate=Decimal("14"))
                net = q5(q5(unit * qty) - disc)
                total = q5(net + q5(net * Decimal("0.14")))
                expected = paid if incl else q5(paid * Decimal("1.14"))
                assert abs(total - expected) <= Decimal("0.005")


class TestSale:
    async def test_a_sale_becomes_a_receipt_that_totals_what_the_till_charged(self, db, tenant_ctx):
        await _configure(db, tenant_ctx.tenant_id)
        _, _, sold, receipt = await _sold(db, tenant_ctx, price="114.00", qty=2)
        ctx = await build_context(db, tenant_ctx.tenant_id, receipt)
        assert ctx.document_type == "sale_receipt" and ctx.country_code == "EG"
        assert ctx.invoice_number == sold["receipt_number"]
        assert ctx.grand_total == Decimal(sold["grand_total"]) == Decimal("228.00")
        line = ctx.lines[0]
        assert (line.unit_price, line.tax_amount, line.total) == (
            Decimal("100.00000"),
            Decimal("28.00000"),
            Decimal("228.00000"),
        )
        assert (line.item_code_type, line.item_code, line.unit_code) == ("EGS", "EG-1001", "EA")
        assert ctx.seller.tax_id == "674859545" and ctx.extras["payment_method"] == "C"

    async def test_a_cashier_discount_flows_through_and_still_totals_what_was_charged(
        self, db, tenant_ctx
    ):
        await _configure(db, tenant_ctx.tenant_id)
        _, _, sold, receipt = await _sold(db, tenant_ctx, price="114.00", qty=2, pct="10")
        ctx = await build_context(db, tenant_ctx.tenant_id, receipt)
        assert Decimal(sold["grand_total"]) == Decimal("205.20")
        assert ctx.grand_total == Decimal("205.20")
        assert ctx.lines[0].discount == Decimal("20.00000")

    async def test_vat_exclusive_prices_add_the_tax_on_top(self, db, tenant_ctx):
        await _configure(db, tenant_ctx.tenant_id, **{"einvoice.prices_include_vat": False})
        _, _, _, receipt = await _sold(db, tenant_ctx, price="100.00", qty=1)
        ctx = await build_context(db, tenant_ctx.tenant_id, receipt)
        assert ctx.lines[0].unit_price == Decimal("100.00000")
        assert ctx.grand_total == Decimal("114.00")

    async def test_the_default_payment_method_comes_from_the_store_setting(self, db, tenant_ctx):
        await _configure(db, tenant_ctx.tenant_id, **{"einvoice.default_payment_method": "V"})
        _, _, _, receipt = await _sold(db, tenant_ctx)
        ctx = await build_context(db, tenant_ctx.tenant_id, receipt)
        assert ctx.extras["payment_method"] == "V"

    async def test_the_vat_rate_comes_from_the_tax_table_not_a_literal(self, db, tenant_ctx):
        await _configure(db, tenant_ctx.tenant_id)
        _, _, _, receipt = await _sold(db, tenant_ctx)
        ctx = await build_context(db, tenant_ctx.tenant_id, receipt)
        assert ctx.lines[0].tax_rate == Decimal("0.14000")

    async def test_egs_wins_over_gs1_when_a_variant_has_both(self, db, tenant_ctx):
        await _configure(db, tenant_ctx.tenant_id)
        _, variant, _, receipt = await _sold(db, tenant_ctx)
        await _coded(db, tenant_ctx.tenant_id, variant, code="6221234567890", kind="gs1")
        ctx = await build_context(db, tenant_ctx.tenant_id, receipt)
        assert (ctx.lines[0].item_code_type, ctx.lines[0].item_code) == ("EGS", "EG-1001")

    async def test_a_gs1_only_variant_uses_gs1(self, db, tenant_ctx):
        await _configure(db, tenant_ctx.tenant_id)
        _, _, _, receipt = await _sold(db, tenant_ctx, coded=False)
        variant_id = (
            await db.execute(
                sa.text("select variant_id from order_items where order_id = :o"),
                {"o": str(receipt.order_id)},
            )
        ).scalar_one()
        await CatalogService.add_identifier(
            db, tenant_ctx.tenant_id, variant_id, "gs1", "6221234567890"
        )
        ctx = await build_context(db, tenant_ctx.tenant_id, receipt)
        assert (ctx.lines[0].item_code_type, ctx.lines[0].item_code) == ("GS1", "6221234567890")


class TestWhatItRefusesToGuess:
    async def test_a_line_without_a_registered_item_code_waits_and_says_which(self, db, tenant_ctx):
        await _configure(db, tenant_ctx.tenant_id)
        _, _, _, receipt = await _sold(db, tenant_ctx, coded=False)
        with pytest.raises(NotReady, match="no registered item code"):
            await build_context(db, tenant_ctx.tenant_id, receipt)

    async def test_an_internal_sku_is_never_passed_off_as_the_registered_item_code(
        self, db, tenant_ctx
    ):
        await _configure(db, tenant_ctx.tenant_id)
        _, _, _, receipt = await _sold(db, tenant_ctx, coded=False)
        await db.execute(
            sa.text("update order_items set sku = 'TSH-L-BLK' where order_id = :o"),
            {"o": str(receipt.order_id)},
        )
        with pytest.raises(NotReady, match="TSH-L-BLK: no registered item code"):
            await build_context(db, tenant_ctx.tenant_id, receipt)

    async def test_a_scan_barcode_is_not_taken_for_an_item_code(self, db, tenant_ctx):
        await _configure(db, tenant_ctx.tenant_id)
        _, _, _, receipt = await _sold(db, tenant_ctx, coded=False)
        variant_id = (
            await db.execute(
                sa.text("select variant_id from order_items where order_id = :o"),
                {"o": str(receipt.order_id)},
            )
        ).scalar_one()
        await CatalogService.add_identifier(
            db, tenant_ctx.tenant_id, variant_id, "ean", "6221234567890"
        )
        with pytest.raises(NotReady, match="no registered item code"):
            await build_context(db, tenant_ctx.tenant_id, receipt)

    async def test_a_store_without_a_tax_registration_number_waits(self, db, tenant_ctx):
        await SettingsService(db, tenant_ctx.tenant_id).set("business.legal_name", "متجر")
        _, _, _, receipt = await _sold(db, tenant_ctx)
        with pytest.raises(NotReady, match="tax registration number"):
            await build_context(db, tenant_ctx.tenant_id, receipt)

    async def test_a_store_without_a_registered_name_waits(self, db, tenant_ctx):
        await SettingsService(db, tenant_ctx.tenant_id).set("business.tax_id", "674859545")
        _, _, _, receipt = await _sold(db, tenant_ctx)
        with pytest.raises(NotReady, match="registered name"):
            await build_context(db, tenant_ctx.tenant_id, receipt)

    async def test_settings_default_to_off_vat_inclusive_and_cash(self, db, tenant_ctx):
        s = await eta_settings(db, tenant_ctx.tenant_id)
        assert (s.enabled, s.prices_include_vat, s.default_payment_method) == (False, True, "C")


class TestReturn:
    async def _returned(self, db, tenant_ctx, *, with_original_receipt=True):
        from app.modules.einvoice.models import EInvoiceDevice
        from app.modules.einvoice.service import EInvoiceService
        from tests.test_eta_db_layer import _ctx, _device

        tid = tenant_ctx.tenant_id
        await _configure(db, tid)
        shift, variant, sold, sale_receipt = await _sold(db, tenant_ctx, price="114.00", qty=3)
        if with_original_receipt:
            dev = await _device(db, tid)
            assert isinstance(dev, EInvoiceDevice)
            await EInvoiceService.issue_einvoice(
                db, tid, _ctx(tid, sale_receipt.number), device_id=dev.id
            )
        returned = await PosService.return_sale(
            db,
            tid,
            shift.id,
            order_id=sold["order_id"],
            lines=[{"variant_id": str(variant.id), "quantity": 1}],
        )
        receipt = (
            await db.execute(sa.select(PosReceipt).where(PosReceipt.id == returned["receipt_id"]))
        ).scalar_one()
        return sale_receipt, returned, receipt

    async def test_a_return_refers_to_the_original_sales_receipt_and_values_the_goods_back(
        self, db, tenant_ctx
    ):
        sale_receipt, returned, receipt = await self._returned(db, tenant_ctx)
        ctx = await build_context(db, tenant_ctx.tenant_id, receipt)
        assert ctx.document_type == "return_receipt"
        assert ctx.original_reference == sale_receipt.number
        assert ctx.original_uuid and len(ctx.original_uuid) >= 8
        assert ctx.grand_total == Decimal(returned["refunded_total"]) == Decimal("114.00")
        assert ctx.lines[0].quantity == Decimal(1)

    async def test_a_return_is_valued_at_what_was_paid_not_at_the_shelf_price(self, db, tenant_ctx):
        from app.modules.einvoice.service import EInvoiceService
        from tests.test_eta_db_layer import _ctx, _device

        tid = tenant_ctx.tenant_id
        await _configure(db, tid)
        shift, variant, sold, sale_receipt = await _sold(
            db, tenant_ctx, price="114.00", qty=3, pct="10"
        )
        dev = await _device(db, tid)
        await EInvoiceService.issue_einvoice(
            db, tid, _ctx(tid, sale_receipt.number), device_id=dev.id
        )
        returned = await PosService.return_sale(
            db,
            tid,
            shift.id,
            order_id=sold["order_id"],
            lines=[{"variant_id": str(variant.id), "quantity": 2}],
        )
        receipt = (
            await db.execute(sa.select(PosReceipt).where(PosReceipt.id == returned["receipt_id"]))
        ).scalar_one()
        ctx = await build_context(db, tid, receipt)
        # 2 of 3 units sold at 10% off: 2 x 114 x 0.9 = 205.20, never the shelf 228
        assert Decimal(returned["refunded_total"]) == Decimal("205.20")
        assert ctx.grand_total == Decimal("205.20")
        assert ctx.lines[0].quantity == Decimal(2)

    async def test_a_return_whose_original_was_never_sent_as_an_e_receipt_waits(
        self, db, tenant_ctx
    ):
        _, _, receipt = await self._returned(db, tenant_ctx, with_original_receipt=False)
        with pytest.raises(NotReady, match="has no e-receipt to refer to"):
            await build_context(db, tenant_ctx.tenant_id, receipt)

    async def test_the_receipt_ids_are_unique_per_tenant(self):
        assert uuid.uuid4() != uuid.uuid4()


class TestTheMerchantDecides:
    """Everything about the shop itself is a store setting, and each one changes the receipt."""

    async def test_an_exempt_store_charges_no_vat_even_with_vat_inclusive_prices(
        self, db, tenant_ctx
    ):
        await _configure(db, tenant_ctx.tenant_id, **{"einvoice.vat_category": "exempt"})
        _, _, sold, receipt = await _sold(db, tenant_ctx, price="114.00", qty=1)
        ctx = await build_context(db, tenant_ctx.tenant_id, receipt)
        line = ctx.lines[0]
        assert line.vat_subtype == "V003" and line.tax_amount == Decimal(0)
        assert line.unit_price == Decimal("114.00000")  # not divided by 1.14
        assert ctx.grand_total == Decimal(sold["grand_total"]) == Decimal("114.00")

    async def test_a_non_taxable_store_uses_the_non_taxable_subtype_and_no_vat(
        self, db, tenant_ctx
    ):
        await _configure(db, tenant_ctx.tenant_id, **{"einvoice.vat_category": "non_taxable"})
        _, _, _, receipt = await _sold(db, tenant_ctx, price="50.00", qty=2)
        ctx = await build_context(db, tenant_ctx.tenant_id, receipt)
        assert ctx.lines[0].vat_subtype == "V004" and ctx.tax_total == Decimal(0)
        assert ctx.grand_total == Decimal("100.00")

    async def test_the_unit_of_measure_is_the_merchants_choice(self, db, tenant_ctx):
        await _configure(db, tenant_ctx.tenant_id, **{"einvoice.unit_code": "KGM"})
        _, _, _, receipt = await _sold(db, tenant_ctx)
        ctx = await build_context(db, tenant_ctx.tenant_id, receipt)
        assert ctx.lines[0].unit_code == "KGM"

    async def test_the_delivery_mode_is_the_merchants_choice(self, db, tenant_ctx):
        await _configure(db, tenant_ctx.tenant_id, **{"einvoice.delivery_mode": "TC"})
        _, _, _, receipt = await _sold(db, tenant_ctx)
        ctx = await build_context(db, tenant_ctx.tenant_id, receipt)
        assert ctx.extras["delivery_mode"] == "TC"

    async def test_the_branch_comes_from_the_store_settings(self, db, tenant_ctx):
        await _configure(
            db,
            tenant_ctx.tenant_id,
            **{
                "einvoice.branch_code": "7",
                "einvoice.activity_code": "4771",
                "einvoice.branch_governate": "Cairo",
                "einvoice.branch_region_city": "Nasr City",
                "einvoice.branch_street": "Abbas El Akkad",
                "einvoice.branch_building_number": "12",
            },
        )
        _, _, _, receipt = await _sold(db, tenant_ctx)
        ctx = await build_context(db, tenant_ctx.tenant_id, receipt)
        assert ctx.extras["store_profile"] == {
            "branch_code": "7",
            "activity_code": "4771",
            "branch_address": {
                "governate": "Cairo",
                "region_city": "Nasr City",
                "street": "Abbas El Akkad",
                "building_number": "12",
            },
        }

    async def test_a_value_set_on_the_till_itself_overrides_the_store_setting(self):
        from app.modules.einvoice.models import EInvoiceDevice
        from app.modules.einvoice.providers.eta.context import device_profile

        store = {
            "branch_code": "7",
            "activity_code": "4771",
            "branch_address": {"governate": "Cairo", "street": "Main"},
        }
        till = EInvoiceDevice(
            device_serial="R2",
            metadata_info={"eta": {"branch_code": "9", "branch_address": {"street": "Annex"}}},
        )
        profile = device_profile(till, store)
        assert profile.branch_code == "9" and profile.activity_code == "4771"
        assert profile.address.street == "Annex" and profile.address.governate == "Cairo"

    async def test_nothing_is_invented_when_the_merchant_has_not_filled_it_in(self):
        from app.modules.einvoice.models import EInvoiceDevice
        from app.modules.einvoice.providers.eta.context import device_profile

        profile = device_profile(EInvoiceDevice(device_serial="R1", metadata_info={}), None)
        assert profile.branch_code == "" and profile.activity_code == ""
        assert profile.address.governate == "" and profile.address.street == ""

    async def test_an_unknown_choice_is_refused_by_the_settings_layer(self, db, tenant_ctx):
        svc = SettingsService(db, tenant_ctx.tenant_id)
        with pytest.raises(ValidationError):
            await svc.set("einvoice.vat_category", "whatever")
        with pytest.raises(ValidationError):
            await svc.set("einvoice.delivery_mode", "XX")
        with pytest.raises(ValidationError):
            await svc.set("einvoice.warn_hours_before_deadline", 0)


class TestTheFrontendNamesEveryChoice:
    """The settings screen names coded choices in plain Arabic; none may be left out."""

    def test_every_allowed_value_has_an_arabic_name_in_the_screen(self):
        import pathlib
        import re

        from app.modules.settings.registry import list_definitions

        root = pathlib.Path(__file__).resolve().parents[2]
        src = (root / "frontend/src/cashier/api/shopPolicy.js").read_text(encoding="utf-8")
        for d in list_definitions(domain="einvoice"):
            if d.type.value != "enum":
                continue
            block = re.search(rf'"{re.escape(d.key)}": \{{(.*?)\n  \}}', src, re.S)
            assert block, f"{d.key} has no Arabic names in shopPolicy.js"
            named = set(re.findall(r"^\s+(\w+):", block.group(1), re.M))
            assert named == set(d.allowed_values), (d.key, named ^ set(d.allowed_values))
