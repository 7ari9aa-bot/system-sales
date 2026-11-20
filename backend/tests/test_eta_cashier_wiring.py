"""The cashier really hands its sales, returns and exchanges to the e-receipt layer.

Two promises matter more than any detail: with the feature off nothing changes for the store, and
no matter what is missing on the e-receipt side the sale itself always goes through.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
import sqlalchemy as sa

import app.core.model_registry  # noqa: F401
from app.modules.catalog.service import CatalogService
from app.modules.einvoice.models import EInvoiceDevice, EInvoiceDocument
from app.modules.pos.models import PosReceipt
from app.modules.pos.service import PosService
from app.modules.settings.service import SettingsService
from tests._pos_sell import sell as pos_sell
from tests.test_pos_returns import _customer, _register, _sellable_variant

pytestmark = pytest.mark.asyncio

BRANCH = {
    "einvoice.branch_code": "1",
    "einvoice.activity_code": "4771",
    "einvoice.branch_governate": "Cairo",
    "einvoice.branch_region_city": "Nasr City",
    "einvoice.branch_street": "16 street",
    "einvoice.branch_building_number": "14",
}
SHOP = {"business.tax_id": "674859545", "business.legal_name": "متجر الملابس"}


async def _shop(db, tid, *, enabled=True, till=True, code=True, **extra):
    """A store with a till; returns (register, shift, variant). Settings are the merchant's."""
    svc = SettingsService(db, tid)
    for key, value in {**SHOP, **BRANCH, "einvoice.eta_enabled": enabled, **extra}.items():
        await svc.set(key, value)

    class Ctx:
        tenant_id = tid

    register = await _register(db, Ctx)
    if till:
        db.add(
            EInvoiceDevice(
                tenant_id=tid,
                device_name="Till",
                device_serial=register.code,
                country_code="EG",
                provider_type="eta",
                status="active",
            )
        )
    shift = await PosService.open_session(db, tid, register.id)
    variant = await _sellable_variant(db, Ctx, price="114.00", stock=50)
    if code:
        await CatalogService.add_identifier(db, tid, variant.id, "egs", "EG-1001")
    await db.flush()
    return register, shift, variant, Ctx


async def _sell(db, tid, shift, variant, ctx, qty=2):
    customer = await _customer(db, ctx)
    return await pos_sell(
        db,
        tid,
        shift.id,
        customer_id=customer.id,
        items=[{"variant_id": str(variant.id), "quantity": qty}],
    )


async def _docs(db, tid) -> list[EInvoiceDocument]:
    return list(
        (
            await db.execute(
                sa.select(EInvoiceDocument)
                .where(EInvoiceDocument.tenant_id == tid)
                .order_by(EInvoiceDocument.icv)
            )
        ).scalars()
    )


class TestSale:
    async def test_a_sale_is_stored_as_an_e_receipt_for_the_registers_till(self, db, tenant_ctx):
        tid = tenant_ctx.tenant_id
        register, shift, variant, ctx = await _shop(db, tid)
        sold = await _sell(db, tid, shift, variant, ctx)
        docs = await _docs(db, tid)
        assert [d.invoice_number for d in docs] == [sold["receipt_number"]]
        doc = docs[0]
        assert doc.document_type == "sale_receipt" and doc.provider_type == "eta"
        assert doc.receipt_id == sold["receipt_id"] and doc.order_id == sold["order_id"]
        assert doc.icv == 1 and doc.status in {"pending", "signed"}  # stored, not yet sent
        assert register.code  # the till is found by the register's code

    async def test_the_stored_receipt_carries_the_merchants_branch_not_a_default(
        self, db, tenant_ctx
    ):
        import json

        tid = tenant_ctx.tenant_id
        _, shift, variant, ctx = await _shop(db, tid)
        await _sell(db, tid, shift, variant, ctx)
        body = json.loads((await _docs(db, tid))[0].raw_payload)
        assert body["seller"]["branchCode"] == "1" and body["seller"]["activityCode"] == "4771"
        assert body["seller"]["branchAddress"]["regionCity"] == "Nasr City"
        assert body["seller"]["rin"] == "674859545"
        assert body["totalAmount"] == 228 or Decimal(str(body["totalAmount"])) == Decimal("228")

    async def test_two_sales_chain_on_the_same_till(self, db, tenant_ctx):
        import json

        tid = tenant_ctx.tenant_id
        _, shift, variant, ctx = await _shop(db, tid)
        await _sell(db, tid, shift, variant, ctx, qty=1)
        await _sell(db, tid, shift, variant, ctx, qty=1)
        first, second = await _docs(db, tid)
        assert (first.icv, second.icv) == (1, 2)
        assert json.loads(second.raw_payload)["header"]["previousUUID"] == first.invoice_hash


class TestOffByDefault:
    async def test_with_the_feature_off_nothing_is_issued_and_the_sale_is_unchanged(
        self, db, tenant_ctx
    ):
        tid = tenant_ctx.tenant_id
        _, shift, variant, ctx = await _shop(db, tid, enabled=False)
        sold = await _sell(db, tid, shift, variant, ctx)
        assert sold["grand_total"] == "228.00" and await _docs(db, tid) == []

    async def test_a_store_that_never_touched_the_settings_is_unaffected(self, db, tenant_ctx):
        tid = tenant_ctx.tenant_id

        class Ctx:
            tenant_id = tid

        register = await _register(db, Ctx)
        shift = await PosService.open_session(db, tid, register.id)
        variant = await _sellable_variant(db, Ctx, price="25.00", stock=5)
        sold = await _sell(db, tid, shift, variant, Ctx, qty=1)
        assert sold["receipt_number"] and await _docs(db, tid) == []


class TestTheSaleAlwaysGoesThrough:
    """A customer is at the counter. Whatever is missing, the sale stands."""

    async def test_no_till_set_up_for_this_register(self, db, tenant_ctx):
        tid = tenant_ctx.tenant_id
        _, shift, variant, ctx = await _shop(db, tid, till=False)
        sold = await _sell(db, tid, shift, variant, ctx)
        assert sold["receipt_number"] and await _docs(db, tid) == []

    async def test_an_item_without_a_registered_code(self, db, tenant_ctx):
        tid = tenant_ctx.tenant_id
        _, shift, variant, ctx = await _shop(db, tid, code=False)
        sold = await _sell(db, tid, shift, variant, ctx)
        assert sold["receipt_number"] and await _docs(db, tid) == []
        assert await db.scalar(
            sa.select(sa.func.count()).select_from(PosReceipt).where(PosReceipt.tenant_id == tid)
        )

    async def test_a_store_with_no_tax_registration_number(self, db, tenant_ctx):
        tid = tenant_ctx.tenant_id
        _, shift, variant, ctx = await _shop(db, tid)
        await SettingsService(db, tid).set("business.tax_id", "")
        sold = await _sell(db, tid, shift, variant, ctx)
        assert sold["receipt_number"] and await _docs(db, tid) == []

    async def test_a_suspended_till_does_not_block_the_sale(self, db, tenant_ctx):
        tid = tenant_ctx.tenant_id
        _, shift, variant, ctx = await _shop(db, tid)
        await db.execute(
            sa.update(EInvoiceDevice)
            .where(EInvoiceDevice.tenant_id == tid)
            .values(status="suspended")
        )
        sold = await _sell(db, tid, shift, variant, ctx)
        assert sold["receipt_number"] and await _docs(db, tid) == []

    async def test_a_crash_inside_the_e_receipt_code_never_reaches_the_cashier(
        self, db, tenant_ctx, monkeypatch
    ):
        import app.modules.einvoice.service as svc_mod

        async def boom(*a, **k):
            raise ValueError("builder exploded")

        monkeypatch.setattr(svc_mod.EInvoiceService, "issue_einvoice", boom)
        tid = tenant_ctx.tenant_id
        _, shift, variant, ctx = await _shop(db, tid)
        sold = await _sell(db, tid, shift, variant, ctx)
        assert sold["receipt_number"] and await _docs(db, tid) == []

    async def test_a_database_error_inside_the_e_receipt_does_not_poison_the_sale(
        self, db, tenant_ctx, monkeypatch
    ):
        from sqlalchemy.exc import IntegrityError

        import app.modules.einvoice.service as svc_mod

        async def boom(session, *a, **k):
            await session.execute(sa.text("select 1/0"))  # a real database error
            raise IntegrityError("x", {}, Exception("y"))

        monkeypatch.setattr(svc_mod.EInvoiceService, "issue_einvoice", boom)
        tid = tenant_ctx.tenant_id
        _, shift, variant, ctx = await _shop(db, tid)
        sold = await _sell(db, tid, shift, variant, ctx)
        # the transaction is still usable: the next sale works and the first is stored
        again = await _sell(db, tid, shift, variant, ctx)
        assert sold["receipt_number"] and again["receipt_number"]


class TestTheRealErrorTypes:
    """The failures that can actually come out of issuing, not just a generic ValueError."""

    @pytest.mark.parametrize(
        "make",
        [
            lambda: __import__("app.core.errors", fromlist=["x"]).ConflictError("already issued"),
            lambda: __import__("app.core.errors", fromlist=["x"]).NotFoundError("no device"),
            lambda: __import__(
                "app.modules.einvoice.providers.eta.client", fromlist=["x"]
            ).EtaTransientError("authority is down"),
            lambda: __import__(
                "app.modules.einvoice.providers.eta.client", fromlist=["x"]
            ).EtaAuthError("bad credentials"),
        ],
        ids=["duplicate-number", "device-missing", "authority-down", "bad-credentials"],
    )
    async def test_none_of_them_reaches_the_cashier(self, db, tenant_ctx, monkeypatch, make):
        import app.modules.einvoice.service as svc_mod

        async def boom(*a, **k):
            raise make()

        monkeypatch.setattr(svc_mod.EInvoiceService, "issue_einvoice", boom)
        tid = tenant_ctx.tenant_id
        _, shift, variant, ctx = await _shop(db, tid)
        sold = await _sell(db, tid, shift, variant, ctx)
        assert sold["receipt_number"] and await _docs(db, tid) == []


class TestSeveralRegisters:
    async def test_each_register_sends_through_its_own_till_and_its_own_chain(self, db, tenant_ctx):
        tid = tenant_ctx.tenant_id
        _, shift_a, variant, ctx = await _shop(db, tid)
        register_b = await _register(db, ctx)
        db.add(
            EInvoiceDevice(
                tenant_id=tid,
                device_name="Till B",
                device_serial=register_b.code,
                country_code="EG",
                provider_type="eta",
                status="active",
            )
        )
        shift_b = await PosService.open_session(db, tid, register_b.id)
        await db.flush()
        a1 = await _sell(db, tid, shift_a, variant, ctx, qty=1)
        b1 = await _sell(db, tid, shift_b, variant, ctx, qty=1)
        a2 = await _sell(db, tid, shift_a, variant, ctx, qty=1)
        by_number = {d.invoice_number: d for d in await _docs(db, tid)}
        serial_of = {
            d.id: d.device_serial for d in (await db.execute(sa.select(EInvoiceDevice))).scalars()
        }
        assert (
            serial_of[by_number[a1["receipt_number"]].device_id]
            != serial_of[by_number[b1["receipt_number"]].device_id]
        )
        assert (
            by_number[a1["receipt_number"]].device_id == by_number[a2["receipt_number"]].device_id
        )
        assert (by_number[a1["receipt_number"]].icv, by_number[a2["receipt_number"]].icv) == (1, 2)
        assert by_number[b1["receipt_number"]].icv == 1  # its own chain starts at 1


class TestReturnAndExchange:
    async def test_a_return_refers_to_the_original_receipt_and_chains_after_it(
        self, db, tenant_ctx
    ):
        import json

        tid = tenant_ctx.tenant_id
        _, shift, variant, ctx = await _shop(db, tid)
        sold = await _sell(db, tid, shift, variant, ctx, qty=2)
        returned = await PosService.return_sale(
            db,
            tid,
            shift.id,
            order_id=sold["order_id"],
            lines=[{"variant_id": str(variant.id), "quantity": 1}],
        )
        sale_doc, return_doc = await _docs(db, tid)
        assert return_doc.document_type == "return_receipt"
        assert return_doc.invoice_number == returned["receipt_number"]
        body = json.loads(return_doc.raw_payload)
        assert body["header"]["referenceUUID"] == sale_doc.invoice_hash
        assert body["header"]["previousUUID"] == sale_doc.invoice_hash
        assert Decimal(str(body["totalAmount"])) == Decimal("114")

    async def test_a_return_still_goes_through_when_its_e_receipt_cannot_be_built(
        self, db, tenant_ctx
    ):
        tid = tenant_ctx.tenant_id
        _, shift, variant, ctx = await _shop(db, tid, enabled=False)
        sold = await _sell(db, tid, shift, variant, ctx, qty=2)
        await SettingsService(db, tid).set("einvoice.eta_enabled", True)  # turned on afterwards
        returned = await PosService.return_sale(
            db,
            tid,
            shift.id,
            order_id=sold["order_id"],
            lines=[{"variant_id": str(variant.id), "quantity": 1}],
        )
        assert returned["receipt_number"] and await _docs(db, tid) == []

    async def test_an_exchange_sends_the_return_half_before_the_new_sale(self, db, tenant_ctx):
        tid = tenant_ctx.tenant_id
        _, shift, variant, ctx = await _shop(db, tid)
        sold = await _sell(db, tid, shift, variant, ctx, qty=2)
        new_variant = await _sellable_variant(db, ctx, price="228.00", stock=10)
        await CatalogService.add_identifier(db, tid, new_variant.id, "egs", "EG-2002")
        result = await PosService.exchange(
            db,
            tid,
            shift.id,
            order_id=sold["order_id"],
            return_lines=[{"variant_id": str(variant.id), "quantity": 1}],
            new_lines=[{"variant_id": str(new_variant.id), "quantity": 1}],
        )
        sale_doc, return_doc, new_doc = await _docs(db, tid)
        assert [d.document_type for d in (sale_doc, return_doc, new_doc)] == [
            "sale_receipt",
            "return_receipt",
            "sale_receipt",
        ]
        assert return_doc.invoice_number == result["return_receipt_number"]
        assert (sale_doc.icv, return_doc.icv, new_doc.icv) == (1, 2, 3)
