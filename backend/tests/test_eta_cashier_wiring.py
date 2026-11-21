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
CONFIRMED = {"einvoice.settings_confirmed": True}


async def _shop(db, tid, *, enabled=True, till=True, code=True, **extra):
    """A store with a till; returns (register, shift, variant). Settings are the merchant's."""
    svc = SettingsService(db, tid)
    for key, value in {
        **SHOP,
        **BRANCH,
        **CONFIRMED,
        "einvoice.eta_enabled": enabled,
        **extra,
    }.items():
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


class TestTheMerchantMustConfirmTheMoneySettings:
    """Prices with or without VAT, the VAT category and the fallback payment method all differ
    from shop to shop. Their starting values are only suggestions, so nothing is issued until
    the merchant has looked at them and confirmed."""

    async def test_enabled_but_not_confirmed_issues_nothing_and_the_sale_goes_through(
        self, db, tenant_ctx
    ):
        tid = tenant_ctx.tenant_id
        _r, shift, variant, ctx = await _shop(db, tid, **{"einvoice.settings_confirmed": False})
        sold = await _sell(db, tid, shift, variant, ctx)
        assert sold["receipt_id"]
        assert await _docs(db, tid) == []

    async def test_the_reason_names_what_to_do(self, db, tenant_ctx):
        from app.modules.pos.eta_adapter import issue_for_receipt

        tid = tenant_ctx.tenant_id
        register, shift, variant, ctx = await _shop(
            db, tid, **{"einvoice.settings_confirmed": False}
        )
        sold = await _sell(db, tid, shift, variant, ctx)
        receipt = (
            await db.execute(sa.select(PosReceipt).where(PosReceipt.id == sold["receipt_id"]))
        ).scalar_one()
        result = await issue_for_receipt(db, tid, receipt, register_code=register.code)
        assert result.issued is False and "confirm" in (result.skipped or "")

    async def test_confirming_turns_it_on(self, db, tenant_ctx):
        tid = tenant_ctx.tenant_id
        _r, shift, variant, ctx = await _shop(db, tid)  # _shop confirms by default
        await _sell(db, tid, shift, variant, ctx)
        assert len(await _docs(db, tid)) == 1

    async def test_a_new_shop_starts_unconfirmed(self, db, tenant_ctx):
        from app.modules.pos.eta_adapter import eta_settings

        assert (await eta_settings(db, tenant_ctx.tenant_id)).settings_confirmed is False


class TestShopDetailsTheMerchantHasNotEntered:
    """Branch, activity and address are the merchant's to enter. Left blank they are never
    replaced by a guess: the receipt is not built, the sale still goes through."""

    @pytest.mark.parametrize(
        "blank",
        [
            "einvoice.branch_code",
            "einvoice.activity_code",
            "einvoice.branch_governate",
            "einvoice.branch_region_city",
            "einvoice.branch_street",
            "einvoice.branch_building_number",
        ],
    )
    async def test_a_blank_shop_detail_blocks_the_receipt_not_the_sale(self, db, tenant_ctx, blank):
        tid = tenant_ctx.tenant_id
        _register_row, shift, variant, ctx = await _shop(db, tid, **{blank: ""})
        sold = await _sell(db, tid, shift, variant, ctx)
        assert sold["receipt_id"]  # the customer was served
        # No e-receipt was built: a blank shop detail is never sent to the authority as-is.
        assert await _docs(db, tid) == []


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


class TestReturnOnASaleFromBeforeTheShopJoined:
    async def test_the_whole_path_to_the_authority_works_for_a_reference_less_return(
        self, db, tenant_ctx
    ):
        """Sale, then the shop turns e-receipts on, then the old sale is returned: the return is
        built, stored and ACCEPTED by the (official-rules) mock authority as a reference-less
        return with reason B."""
        import json

        import httpx

        from app.modules.einvoice.providers.eta.delivery import deliver_device
        from app.modules.einvoice.providers.eta.mock_authority import MockAuthority
        from app.modules.einvoice.providers.eta.provider import EtaEInvoiceProvider

        tid = tenant_ctx.tenant_id
        register, shift, variant, ctx = await _shop(db, tid, enabled=False)
        old = await _sell(db, tid, shift, variant, ctx, qty=2)
        await db.execute(
            sa.text("update pos_receipts set issued_at = issued_at - interval '3 days'")
        )
        await SettingsService(db, tid).set("einvoice.eta_enabled", True)
        # the first e-receipt the shop ever issues (so "before" now has a meaning)
        await _sell(db, tid, shift, variant, ctx, qty=1)
        returned = await PosService.return_sale(
            db,
            tid,
            shift.id,
            order_id=old["order_id"],
            lines=[{"variant_id": str(variant.id), "quantity": 1}],
        )
        docs = await _docs(db, tid)
        ret = next(d for d in docs if d.invoice_number == returned["receipt_number"])
        body = json.loads(ret.raw_payload)
        assert ret.document_type == "return_without_reference"
        assert body["documentType"]["receiptType"] == "RWR"
        assert "referenceUUID" not in body["header"]
        assert body["header"]["documentUseReason"] == "B"

        # configure the till for sending and deliver everything through the mock authority
        device = (await db.execute(sa.select(EInvoiceDevice))).scalars().first()
        from tests.test_eta_delivery import CREDS

        device.credentials = {"eta": CREDS}
        await db.flush()

        async def no_sleep(_):
            return None

        mock = MockAuthority(pos_serial=device.device_serial, rin="674859545")
        provider = EtaEInvoiceProvider(
            http=httpx.AsyncClient(transport=mock.transport()), sleep=no_sleep
        )
        report = await deliver_device(db, device.id, provider=provider)

        assert report.rejected == 0 and report.accepted == len(docs)


class TestReferenceLessReturnAgainstTheOfficialPage:
    """Return Receipt Without Reference v1.2, as published: the mock enforces it too."""

    def _doc(self, **header):
        """A complete, valid reference-less return built by the real builder, then altered."""
        import copy
        from datetime import UTC, datetime

        from app.modules.einvoice.providers.eta import builder
        from app.modules.einvoice.providers.eta.codes import ReceiptType, ReturnReason
        from tests.test_eta_ereceipt_core import _receipt

        base = _receipt(
            receipt_type=ReceiptType.RETURN_WITHOUT_REFERENCE,
            return_reason=ReturnReason.BEFORE_ADOPTION,
            sales_issued_at=datetime(2026, 11, 10, 8, 0, tzinfo=UTC),
            reference_uuid="",
        )
        doc = copy.deepcopy(builder.build_receipt(base))
        doc["header"].update(header)
        return doc

    def _errors(self, doc):
        """Only the rules this class is about (CF332-CF335); the rest of the document is not."""
        from app.modules.einvoice.providers.eta.mock_authority import MockAuthority

        found = MockAuthority()._validate(doc, {})
        return {e["code"] for e in found if e["code"] in {"CF332", "CF333", "CF334", "CF335"}}

    def test_reason_must_be_i_or_b(self):
        assert "CF332" in self._errors(self._doc(documentUseReason="X"))

    def test_the_sale_date_is_mandatory(self):
        doc = self._doc()
        del doc["header"]["salesIssuedDateTime"]
        assert "CF333" in self._errors(doc)

    def test_an_empty_reference_is_a_defect_but_an_absent_one_is_fine(self):
        assert "CF334" in self._errors(self._doc(referenceUUID=""))
        assert self._errors(self._doc()) == set()
        assert self._errors(self._doc(referenceUUID="b" * 64)) == set()

    def test_only_this_type_carries_a_reason(self):
        doc = self._doc()
        doc["documentType"]["receiptType"] = "SR"
        assert "CF335" in self._errors(doc)
