"""The e-receipt says how the customer REALLY paid, by the shop's own rule when they split it.

The till records each payment line (``OrderPayment``). The shop's default method is only the
fallback for a sale that recorded no payment (a sale on account, or a till that does not take
payments). A split payment becomes ONE method on the receipt, by a rule the merchant chooses.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
import sqlalchemy as sa

import app.core.model_registry  # noqa: F401
from app.modules.catalog.service import CatalogService
from app.modules.pos.eta_adapter import build_context, eta_settings, payment_method_for
from app.modules.pos.models import PosReceipt
from app.modules.pos.service import PosService
from app.modules.settings.service import SettingsService
from tests.test_pos_take_payments import _sell, _shop

pytestmark = pytest.mark.asyncio

D = Decimal


async def _configure(db, tid, **extra):
    svc = SettingsService(db, tid)
    base = {"business.tax_id": "674859545", "business.legal_name": "متجر الملابس"}
    for key, value in {**base, **extra}.items():
        await svc.set(key, value)


async def _receipt(db, sold):
    return (
        await db.execute(sa.select(PosReceipt).where(PosReceipt.id == sold["receipt_id"]))
    ).scalar_one()


async def _paid_sale(db, tenant_ctx, payments, **settings):
    register, variant, customer = await _shop(
        db, tenant_ctx, methods=("cash", "card", "wallet", "bank_transfer")
    )
    await CatalogService.add_identifier(db, tenant_ctx.tenant_id, variant.id, "egs", "EG-1001")
    await _configure(db, tenant_ctx.tenant_id, **settings)
    sold = await _sell(db, tenant_ctx, register, variant, customer, payments)
    return await _receipt(db, sold), sold


async def _method(db, tenant_ctx, payments, **settings) -> str:
    receipt, _ = await _paid_sale(db, tenant_ctx, payments, **settings)
    ctx = await build_context(db, tenant_ctx.tenant_id, receipt)
    return ctx.extras["payment_method"]


class TestOneMethod:
    async def test_a_card_sale_is_a_card_receipt_whatever_the_shop_default_is(self, db, tenant_ctx):
        got = await _method(
            db,
            tenant_ctx,
            [{"method": "card", "amount": "100.00", "reference": "A1"}],
            **{"einvoice.default_payment_method": "C"},
        )
        assert got == "V"

    async def test_a_cash_sale_is_a_cash_receipt_even_if_the_default_says_card(
        self, db, tenant_ctx
    ):
        got = await _method(
            db,
            tenant_ctx,
            [{"method": "cash", "amount": "100.00", "tendered": "200.00"}],
            **{"einvoice.default_payment_method": "V"},
        )
        assert got == "C"

    @pytest.mark.parametrize("method", ["wallet", "bank_transfer"])
    async def test_a_wallet_or_a_transfer_has_no_code_of_its_own_so_it_is_other(
        self, db, tenant_ctx, method
    ):
        got = await _method(
            db, tenant_ctx, [{"method": method, "amount": "100.00", "reference": "R9"}]
        )
        assert got == "O"


class TestSplitPayment:
    SPLIT = [
        {"method": "cash", "amount": "14.00", "tendered": "14.00"},
        {"method": "card", "amount": "86.00", "reference": "A1"},
    ]

    async def test_by_default_the_method_that_paid_the_most_wins(self, db, tenant_ctx):
        assert await _method(db, tenant_ctx, self.SPLIT) == "V"

    async def test_the_default_rule_is_the_largest_amount(self, db, tenant_ctx):
        assert (await eta_settings(db, tenant_ctx.tenant_id)).split_payment_rule == "largest"

    async def test_the_shop_can_ask_for_cash_whenever_any_cash_was_taken(self, db, tenant_ctx):
        got = await _method(
            db, tenant_ctx, self.SPLIT, **{"einvoice.split_payment_rule": "cash_first"}
        )
        assert got == "C"

    async def test_cash_first_with_no_cash_still_picks_the_largest(self, db, tenant_ctx):
        got = await _method(
            db,
            tenant_ctx,
            [
                {"method": "wallet", "amount": "20.00", "reference": "W"},
                {"method": "card", "amount": "80.00", "reference": "A1"},
            ],
            **{"einvoice.split_payment_rule": "cash_first"},
        )
        assert got == "V"

    async def test_two_methods_that_share_a_code_add_up_before_they_compete(self, db, tenant_ctx):
        # wallet 60 + bank transfer 30 are both "other" (90), which beats cash 10.
        got = await _method(
            db,
            tenant_ctx,
            [
                {"method": "cash", "amount": "10.00", "tendered": "10.00"},
                {"method": "wallet", "amount": "60.00", "reference": "W"},
                {"method": "bank_transfer", "amount": "30.00", "reference": "B"},
            ],
        )
        assert got == "O"

    async def test_an_exact_tie_goes_to_cash_then_card_never_to_chance(self, db, tenant_ctx):
        tie = [
            {"method": "card", "amount": "50.00", "reference": "A1"},
            {"method": "cash", "amount": "50.00", "tendered": "50.00"},
        ]
        assert await _method(db, tenant_ctx, tie) == "C"


class TestOnlyRealMoneyCounts:
    async def test_a_payment_that_did_not_go_through_is_not_how_they_paid(self, db, tenant_ctx):
        from app.modules.orders.models import OrderPayment

        receipt, _ = await _paid_sale(
            db, tenant_ctx, [{"method": "cash", "amount": "100.00", "tendered": "100.00"}]
        )
        # A second attempt by card that the bank declined, bigger than nothing but never captured.
        db.add(
            OrderPayment(
                tenant_id=tenant_ctx.tenant_id,
                order_id=receipt.order_id,
                method="card",
                status="failed",
                amount=500,
            )
        )
        await db.flush()
        ctx = await build_context(db, tenant_ctx.tenant_id, receipt)
        assert ctx.extras["payment_method"] == "C"


class TestNothingWasRecorded:
    async def test_no_payment_on_the_sale_falls_back_to_the_shop_default(self, db, tenant_ctx):
        register, variant, customer = await _shop(db, tenant_ctx, take_payments=False)
        await CatalogService.add_identifier(db, tenant_ctx.tenant_id, variant.id, "egs", "EG-1")
        await _configure(db, tenant_ctx.tenant_id, **{"einvoice.default_payment_method": "V"})
        sold = await PosService.record_sale(
            db,
            tenant_ctx.tenant_id,
            register.id,
            items=[{"variant_id": str(variant.id), "quantity": 1}],
            customer_id=customer.id,
            actor_user_id=tenant_ctx.user.id,
        )
        ctx = await build_context(db, tenant_ctx.tenant_id, await _receipt(db, sold))
        assert ctx.extras["payment_method"] == "V"

    async def test_the_pure_rule_with_no_lines_is_the_fallback(self):
        assert payment_method_for([], rule="largest", fallback="CC") == "CC"


class TestAReturnFollowsTheOriginalPayment:
    async def test_a_return_goes_back_the_way_the_sale_was_paid(self, db, tenant_ctx):
        register, variant, customer = await _shop(db, tenant_ctx)
        await CatalogService.add_identifier(db, tenant_ctx.tenant_id, variant.id, "egs", "EG-1")
        await _configure(db, tenant_ctx.tenant_id, **{"einvoice.default_payment_method": "C"})
        sold = await _sell(
            db,
            tenant_ctx,
            register,
            variant,
            customer,
            [{"method": "card", "amount": "100.00", "reference": "A1"}],
        )
        from app.modules.einvoice.service import EInvoiceService
        from tests.test_eta_db_layer import _ctx, _device

        sale_receipt = await _receipt(db, sold)
        device = await _device(db, tenant_ctx.tenant_id)
        await EInvoiceService.issue_einvoice(
            db,
            tenant_ctx.tenant_id,
            _ctx(tenant_ctx.tenant_id, sale_receipt.number),
            device_id=device.id,
        )
        shift = await PosService._today_session(db, tenant_ctx.tenant_id, register)
        returned = await PosService.return_sale(
            db,
            tenant_ctx.tenant_id,
            shift.id,
            order_id=sold["order_id"],
            lines=[{"variant_id": str(variant.id), "quantity": 1}],
        )
        ctx = await build_context(db, tenant_ctx.tenant_id, await _receipt(db, returned))
        assert ctx.extras["payment_method"] == "V"
