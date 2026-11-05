"""The deposit POLICY half: a saved rule, its versions, and the one production
caller of the arithmetic engine in ``orders/deposit.py``.

``test_orders_deposit_rules.py`` proves the arithmetic. These tests prove the
two things arithmetic cannot prove:

1. **A policy is durable state with exactly one active version per tenant.**
   The "one active" rule is a partial unique index, not a service-side check:
   two merchants clicking save at the same moment are two transactions, and the
   only thing that can settle that is Postgres. A test that only exercised
   ``DepositService.save_policy`` would pass against a service that forgot the
   guard, so one case below writes the second active row DIRECTLY.
2. **The amount a customer is asked for comes from the order row and from no
   other place.** ``preview_deposit`` is the engine's production caller — the
   reason ``deposit.py`` is allowed to exist at all under this repo's "a tested
   module must have a caller" rule. Its whole point is that a client-supplied
   amount can never reach it, so it re-reads the stored ``orders`` amounts and
   names the policy VERSION it used. A merchant editing a policy afterwards must
   not be able to move the number a superseded version produced.

Tenancy is asserted the way the rest of the suite asserts it: a second tenant
bound on the same session (RLS is real here — the tests run as the non-BYPASSRLS
``sales_app`` role inside a transaction that is rolled back).
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import bind_tenant
from app.core.idempotency import IdempotencyMiddleware
from app.core.middleware import RateLimitMiddleware
from app.main import create_app
from app.modules.customers.service import CustomerService
from app.modules.errors import NotFoundError, ValidationError
from app.modules.identity.deps import AuthedUser, TenantContext, get_db, get_tenant_ctx
from app.modules.identity.models import Tenant
from app.modules.orders.deposit import (
    BASE_GRAND_TOTAL,
    BASE_ITEMS_AFTER_DISCOUNTS,
    TYPE_FIXED,
    TYPE_NONE,
    TYPE_PERCENTAGE,
)
from app.modules.orders.deposit_service import DepositService
from app.modules.orders.models import DepositPolicy, Order
from app.modules.orders.router import router as orders_router

API = "/api/v1/orders"

# The spec's worked example (Customer Commerce §6.2): 2,000 of goods, 100 of
# shipping, 2,100 grand total, a 20% deposit = 420.00.
GRAND_TOTAL = "2100.00"


async def _policy_count(db: AsyncSession, tenant_id: uuid.UUID) -> int:
    return int(
        (
            await db.execute(
                select(func.count())
                .select_from(DepositPolicy)
                .where(DepositPolicy.tenant_id == tenant_id)
            )
        ).scalar_one()
    )


async def _order(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    subtotal: str = "2000.00",
    discount_total: str = "0.00",
    shipping_total: str = "100.00",
    tax_total: str = "0.00",
    grand_total: str = GRAND_TOTAL,
    currency: str = "EGP",
) -> Order:
    """An order ROW with the amounts the engine is allowed to read.

    Written directly rather than through ``OrderService.create_order``: this
    file is about where a deposit figure comes from, and the checkout path has
    its own tests. The amounts below are the point.
    """
    customer = await CustomerService.get_or_create_by_identity(
        db,
        tenant_id,
        "whatsapp",
        f"wa-{uuid.uuid4().hex[:12]}",
        name="Deposit Buyer",
    )
    order = Order(
        tenant_id=tenant_id,
        customer_id=customer.id,
        number=f"ORD-{uuid.uuid4().hex[:8].upper()}",
        status="pending",
        currency=currency,
        subtotal=Decimal(subtotal),
        discount_total=Decimal(discount_total),
        shipping_total=Decimal(shipping_total),
        tax_total=Decimal(tax_total),
        grand_total=Decimal(grand_total),
    )
    db.add(order)
    await db.flush()
    return order


async def _foreign_tenant(db: AsyncSession) -> uuid.UUID:
    """A second tenant, bound as the current RLS subject on return."""
    other = Tenant(slug=f"dp-{uuid.uuid4().hex[:10]}", name="Deposit Stranger")
    db.add(other)
    await db.flush()
    return other.id


# --------------------------------------------------------------- policies ----


async def test_a_saved_policy_is_the_active_one(db: AsyncSession, tenant_ctx) -> None:
    policy = await DepositService.save_policy(
        db,
        tenant_ctx.tenant_id,
        name="Standard 20%",
        deposit_type=TYPE_PERCENTAGE,
        deposit_value=Decimal("20"),
    )
    assert policy.is_active is True
    assert policy.version == 1
    assert policy.name == "Standard 20%"

    active = await DepositService.get_active(db, tenant_ctx.tenant_id)
    assert active is not None
    assert active.id == policy.id
    # The engine reads the row as values, so the round trip must be lossless.
    assert Decimal(str(active.deposit_value)) == Decimal("20.00")
    assert active.calculation_base == BASE_GRAND_TOTAL


async def test_the_active_policy_is_the_newest_version(db: AsyncSession, tenant_ctx) -> None:
    """Saving a policy twice: the old one stops being active, the new one is v2.

    Both halves matter separately — a save that inserted v2 without deactivating
    v1 would leave two answers to "what do I charge", and one that deactivated
    without bumping the version would destroy the history an order's snapshot
    points at.
    """
    first = await DepositService.save_policy(
        db,
        tenant_ctx.tenant_id,
        name="Standard 20%",
        deposit_type=TYPE_PERCENTAGE,
        deposit_value=Decimal("20"),
    )
    second = await DepositService.save_policy(
        db,
        tenant_ctx.tenant_id,
        name="Heavy 50%",
        deposit_type=TYPE_PERCENTAGE,
        deposit_value=Decimal("50"),
        calculation_base=BASE_ITEMS_AFTER_DISCOUNTS,
    )

    assert first.version == 1
    assert second.version == 2
    assert second.id != first.id

    await db.refresh(first)
    assert first.is_active is False, "the superseded policy is still marked active"

    active = await DepositService.get_active(db, tenant_ctx.tenant_id)
    assert active is not None and active.id == second.id

    listed = await DepositService.list_policies(db, tenant_ctx.tenant_id)
    assert [p.version for p in listed] == [2, 1], "versions must come back newest first"


async def test_a_policy_can_be_turned_off(db: AsyncSession, tenant_ctx) -> None:
    """``none`` is a real answer, and it needs no value.

    A shop that collects nothing must be able to say so; ``deposit_refusal``
    deliberately accepts TYPE_NONE whatever its value holds, so the service must
    not invent a stricter rule of its own.
    """
    policy = await DepositService.save_policy(
        db,
        tenant_ctx.tenant_id,
        name="No deposits (COD shop)",
        deposit_type=TYPE_NONE,
        deposit_value=Decimal("0"),
    )
    assert policy.deposit_type == TYPE_NONE
    assert await DepositService.get_active(db, tenant_ctx.tenant_id) is not None


async def test_the_database_refuses_a_second_active_policy(db: AsyncSession, tenant_ctx) -> None:
    """The one-active-per-tenant rule is enforced by Postgres, not by the service.

    Written as a direct INSERT so the guard cannot be satisfied by a service-side
    check: two concurrent saves are two transactions, and only a unique index
    settles which one wins.
    """
    saved = await DepositService.save_policy(
        db,
        tenant_ctx.tenant_id,
        name="Standard 20%",
        deposit_type=TYPE_PERCENTAGE,
        deposit_value=Decimal("20"),
    )
    tenant_id = tenant_ctx.tenant_id
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            db.add(
                DepositPolicy(
                    tenant_id=tenant_id,
                    name="Rival active policy",
                    deposit_type=TYPE_FIXED,
                    deposit_value=Decimal("100.00"),
                    currency="EGP",
                    calculation_base=BASE_GRAND_TOTAL,
                    is_active=True,
                    version=99,
                )
            )
            await db.flush()

    # The rejected row left nothing behind, and the original is still the answer.
    active = await DepositService.get_active(db, tenant_id)
    assert active is not None and active.id == saved.id and active.version == 1


@pytest.mark.parametrize(
    ("deposit_type", "value", "minimum", "maximum", "reason"),
    [
        (TYPE_PERCENTAGE, "150", None, None, "cannot exceed 100"),
        (TYPE_FIXED, "0", None, None, "needs an amount above zero"),
        (TYPE_PERCENTAGE, "20", "500", "100", "no amount can satisfy both"),
        (TYPE_PERCENTAGE, "20", "-1", None, "must not be negative"),
        ("instalments", "20", None, None, "is not a deposit type this system computes"),
        (TYPE_PERCENTAGE, "20", None, None, None),
    ],
)
async def test_an_invalid_policy_is_refused_and_stores_nothing(
    db: AsyncSession,
    tenant_ctx,
    deposit_type: str,
    value: str,
    minimum: str | None,
    maximum: str | None,
    reason: str | None,
) -> None:
    """A bad policy fails BEFORE any order exists, and fails cleanly.

    The refusal text is the engine's own, verbatim — a merchant must be told why
    in the words that decided it, not a generic 400. And the failed save must
    not leave a half-written row or deactivate the working policy.
    """
    if reason is None:
        # The control: this one is valid, so nothing below may raise.
        await DepositService.save_policy(
            db,
            tenant_ctx.tenant_id,
            name="Valid",
            deposit_type=deposit_type,
            deposit_value=Decimal(value),
        )
        assert await _policy_count(db, tenant_ctx.tenant_id) == 1
        return

    with pytest.raises(ValidationError) as excinfo:
        await DepositService.save_policy(
            db,
            tenant_ctx.tenant_id,
            name="Bad policy",
            deposit_type=deposit_type,
            deposit_value=Decimal(value),
            minimum_deposit=None if minimum is None else Decimal(minimum),
            maximum_deposit=None if maximum is None else Decimal(maximum),
        )
    assert reason in str(excinfo.value)
    assert await _policy_count(db, tenant_ctx.tenant_id) == 0


async def test_a_refused_policy_leaves_the_active_one_untouched(
    db: AsyncSession, tenant_ctx
) -> None:
    """Validation happens before the deactivation, or a typo costs the shop its
    deposit rule while nobody is watching."""
    saved = await DepositService.save_policy(
        db,
        tenant_ctx.tenant_id,
        name="Standard 20%",
        deposit_type=TYPE_PERCENTAGE,
        deposit_value=Decimal("20"),
    )
    with pytest.raises(ValidationError):
        await DepositService.save_policy(
            db,
            tenant_ctx.tenant_id,
            name="Broken",
            deposit_type=TYPE_PERCENTAGE,
            deposit_value=Decimal("150"),
        )

    await db.refresh(saved)
    assert saved.is_active is True
    assert await _policy_count(db, tenant_ctx.tenant_id) == 1


async def test_a_value_that_is_not_a_number_is_a_refusal_not_a_crash(
    db: AsyncSession, tenant_ctx
) -> None:
    """The service's own contract, for callers that are not the router.

    The HTTP model cannot produce this (Pydantic 422s first), but the agent and
    any later worker call ``save_policy`` directly. "Not a number" is the
    merchant's mistake, so it gets the one readable answer the module gives for
    a mistake — a ``ValidationError`` — rather than a bare ``ValueError`` that a
    framework would report as a 500.
    """
    with pytest.raises(ValidationError):
        await DepositService.save_policy(
            db,
            tenant_ctx.tenant_id,
            name="Not a number",
            deposit_type=TYPE_PERCENTAGE,
            deposit_value="twenty",
        )
    assert await _policy_count(db, tenant_ctx.tenant_id) == 0


async def test_the_currency_is_the_tenants_own_never_the_callers(
    db: AsyncSession, tenant_ctx
) -> None:
    """§47: ``save_policy`` takes no currency at all.

    The row carries the tenant's currency, read the same way the order service
    reads it — so a request body cannot smuggle a policy in a currency this
    tenant does not trade in, and the engine's currency gate is never asked to
    price an order in a money the policy was not written for.
    """
    tenant = await db.get(Tenant, tenant_ctx.tenant_id)
    assert tenant is not None
    tenant.currency = "SAR"
    await db.flush()

    policy = await DepositService.save_policy(
        db,
        tenant_ctx.tenant_id,
        name="SAR 20%",
        deposit_type=TYPE_PERCENTAGE,
        deposit_value=Decimal("20"),
    )
    assert policy.currency == "SAR"

    assert "currency" not in set(_save_policy_parameters()), (
        "save_policy must not accept a currency: it is the tenant's, not the caller's"
    )


def _save_policy_parameters() -> list[str]:
    import inspect

    return list(inspect.signature(DepositService.save_policy).parameters)


# ---------------------------------------------------------------- tenancy ----


async def _rls_is_bypassed(db: AsyncSession) -> bool:
    """True when the CONNECTED ROLE bypasses RLS, so no policy is enforced.

    Copied from ``tests/test_scheduler_rls.py``, which documents the harness gap:
    ``conftest`` connects through ``DATABASE_URL_APP_ADMIN``, and where that DSN
    is the owner role the whole suite runs with ``rolbypassrls`` — every RLS
    assertion below would then be vacuous. Skipping loudly is the repo's answer,
    because a silent pass here is exactly how ``scheduled_jobs`` wrote freely for
    its whole life.
    """
    return bool(
        (
            await db.execute(text("SELECT rolbypassrls FROM pg_roles WHERE rolname = current_user"))
        ).scalar()
    )


async def test_deposit_policies_is_force_rls_with_a_tenant_policy(db: AsyncSession) -> None:
    """The database half of tenancy, read off the catalog so ANY role can check it.

    ``test_another_tenant_...`` below can only prove the application layer when
    the connected role bypasses RLS; this proves the policy exists, is FORCE, and
    is bound to ``app.tenant_id`` — the other half of "enforced twice".
    """
    flags = (
        await db.execute(
            text(
                "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                "WHERE relname = 'deposit_policies'"
            )
        )
    ).one()
    assert flags.relrowsecurity is True, "deposit_policies has no RLS"
    assert flags.relforcerowsecurity is True, "deposit_policies is not FORCE RLS"

    policy = (
        await db.execute(
            text(
                "SELECT qual, with_check FROM pg_policies "
                "WHERE tablename = 'deposit_policies' AND policyname = 'tenant_isolation'"
            )
        )
    ).one_or_none()
    assert policy is not None, "deposit_policies lost its tenant_isolation policy"
    assert policy.qual and "app.tenant_id" in policy.qual
    assert policy.with_check and "app.tenant_id" in policy.with_check


async def test_another_tenant_cannot_read_or_deactivate_the_policy(
    db: AsyncSession, tenant_ctx
) -> None:
    """The application-layer half of tenant isolation.

    This repo enforces tenancy twice — the service filters on ``tenant_id`` AND
    the database hides the row — and the two halves are tested separately,
    because a test that only checked one would pass if the other were deleted.
    The row-level half is ``test_rls_hides_the_policy_row_from_a_stranger`` and
    the schema-level half is ``test_deposit_policies_is_force_rls_...``; they
    exist precisely so this one is never credited for hiding a row it only
    filtered out.
    """
    mine = await DepositService.save_policy(
        db,
        tenant_ctx.tenant_id,
        name="Mine 20%",
        deposit_type=TYPE_PERCENTAGE,
        deposit_value=Decimal("20"),
    )
    my_tenant_id = tenant_ctx.tenant_id
    other_id = await _foreign_tenant(db)

    await bind_tenant(db, other_id)
    assert await DepositService.get_active(db, other_id) is None
    assert await DepositService.list_policies(db, other_id) == []

    await bind_tenant(db, my_tenant_id)
    active = await DepositService.get_active(db, my_tenant_id)
    assert active is not None and active.id == mine.id and active.is_active is True


async def test_rls_hides_the_policy_row_from_a_stranger(db: AsyncSession, tenant_ctx) -> None:
    """The database half, on live rows: a stranger's UPDATE matches nothing.

    Written as raw SQL with the row's own id, so no application-layer filter can
    be credited with the result. This is the assertion that a BYPASSRLS test role
    cannot make, so it skips rather than pretending.
    """
    if await _rls_is_bypassed(db):
        pytest.skip(
            "the connected test role bypasses RLS (rolbypassrls), so row hiding "
            "cannot be exercised here — see tests/test_scheduler_rls.py and "
            "conftest's DATABASE_URL_APP_ADMIN"
        )

    mine = await DepositService.save_policy(
        db,
        tenant_ctx.tenant_id,
        name="Mine 20%",
        deposit_type=TYPE_PERCENTAGE,
        deposit_value=Decimal("20"),
    )
    policy_id = str(mine.id)
    my_tenant_id = tenant_ctx.tenant_id
    other_id = await _foreign_tenant(db)
    await bind_tenant(db, other_id)

    touched = await db.execute(
        text("UPDATE deposit_policies SET is_active = false WHERE id = :id"),
        {"id": policy_id},
    )
    assert touched.rowcount == 0, "RLS let another tenant write my policy row"

    # And a foreign tenant id is not an authorisation: the service asks for MY
    # rows while the session is bound as a stranger, and gets nothing back. The
    # application filter alone cannot do this — it would happily match.
    assert await DepositService.get_active(db, my_tenant_id) is None
    assert await DepositService.list_policies(db, my_tenant_id) == []


async def test_a_second_tenant_saving_does_not_disturb_the_first(
    db: AsyncSession, tenant_ctx
) -> None:
    """Version numbering and deactivation are per tenant, not global.

    ``save_policy`` deactivates "the previously active row"; if that query ever
    lost its tenant filter the second merchant's save would silently turn off
    the first merchant's deposit rule.
    """
    mine = await DepositService.save_policy(
        db,
        tenant_ctx.tenant_id,
        name="Mine 20%",
        deposit_type=TYPE_PERCENTAGE,
        deposit_value=Decimal("20"),
    )
    my_tenant_id = tenant_ctx.tenant_id
    other_id = await _foreign_tenant(db)

    await bind_tenant(db, other_id)
    theirs = await DepositService.save_policy(
        db,
        other_id,
        name="Theirs 30%",
        deposit_type=TYPE_PERCENTAGE,
        deposit_value=Decimal("30"),
    )
    assert theirs.version == 1, "versions are numbered per tenant"

    await bind_tenant(db, my_tenant_id)
    await db.refresh(mine)
    assert mine.is_active is True
    assert mine.version == 1
    assert await DepositService.get_active(db, my_tenant_id) is not None


# --------------------------------------------------------- the real caller ----


async def test_preview_prices_the_spec_example_from_the_order_row(
    db: AsyncSession, tenant_ctx
) -> None:
    """20% of a 2,100.00 grand total is 420.00 — and the order row is where it came from."""
    order = await _order(db, tenant_ctx.tenant_id)
    await DepositService.save_policy(
        db,
        tenant_ctx.tenant_id,
        name="Standard 20%",
        deposit_type=TYPE_PERCENTAGE,
        deposit_value=Decimal("20"),
    )

    preview = await DepositService.preview_deposit(db, tenant_ctx.tenant_id, order.id)
    assert preview["deposit"] == Decimal("420.00")
    # ``deposit_paid`` is a LEDGER fact, and a preview has no ledger behind it
    # yet: nothing has been paid, so the balance still collectable is the whole
    # order. The quoted deposit is NOT passed as "paid" — that would report a
    # capture that has not happened.
    assert preview["remaining_balance"] == Decimal("2100.00")
    assert preview["policy_version"] == 1
    assert preview["currency"] == "EGP"
    assert preview["grand_total"] == Decimal(GRAND_TOTAL)


@pytest.mark.parametrize(
    "status,refund_status,refund_amount,expected",
    [
        ("captured", None, "0", "1680.00"),
        ("authorized", None, "0", "2100.00"),
        ("pending", None, "0", "2100.00"),
        ("unknown", None, "0", "2100.00"),
        ("partially_refunded", "processed", "100", "1780.00"),
        ("refunded", "processed", "420", "2100.00"),
        ("captured", "rejected", "100", "1680.00"),
    ],
)
async def test_preview_balance_reads_existing_collections(
    db, tenant_ctx, status, refund_status, refund_amount, expected
):
    from app.modules.orders.models import OrderPayment, Refund

    order = await _order(db, tenant_ctx.tenant_id)
    payment = OrderPayment(
        tenant_id=tenant_ctx.tenant_id,
        order_id=order.id,
        method="cash",
        status=status,
        amount=Decimal("420.00"),
        currency="EGP",
    )
    db.add(payment)
    await db.flush()
    if refund_status:
        db.add(
            Refund(
                tenant_id=tenant_ctx.tenant_id,
                payment_id=payment.id,
                status=refund_status,
                amount=Decimal(refund_amount),
            )
        )
        await db.flush()
    preview = await DepositService.preview_deposit(db, tenant_ctx.tenant_id, order.id)
    assert preview["remaining_balance"] == Decimal(expected)


async def test_preview_floors_items_base_when_discount_also_covers_shipping(db, tenant_ctx):
    order = await _order(
        db,
        tenant_ctx.tenant_id,
        subtotal="100",
        discount_total="150",
        shipping_total="100",
        grand_total="50",
    )
    await DepositService.save_policy(
        db,
        tenant_ctx.tenant_id,
        name="Items only",
        deposit_type=TYPE_PERCENTAGE,
        deposit_value="20",
        calculation_base=BASE_ITEMS_AFTER_DISCOUNTS,
    )
    async with _client(db, tenant_ctx.tenant_id, {"orders:read"}) as client:
        response = await client.get(f"{API}/{order.id}/deposit")
    assert response.status_code == 200
    assert response.json()["deposit"] == "0.00"
    assert response.json()["remaining_balance"] == "50.00"


async def test_preview_uses_the_items_after_discounts_base(db: AsyncSession, tenant_ctx) -> None:
    """The base the merchant chose is the base the engine applies."""
    order = await _order(
        db,
        tenant_ctx.tenant_id,
        subtotal="2000.00",
        discount_total="500.00",
        shipping_total="100.00",
        grand_total="1600.00",
    )
    await DepositService.save_policy(
        db,
        tenant_ctx.tenant_id,
        name="20% of goods",
        deposit_type=TYPE_PERCENTAGE,
        deposit_value=Decimal("20"),
        calculation_base=BASE_ITEMS_AFTER_DISCOUNTS,
    )

    preview = await DepositService.preview_deposit(db, tenant_ctx.tenant_id, order.id)
    # 20% of (2,000 - 500) = 300.00, not 20% of 1,600 = 320.00.
    assert preview["deposit"] == Decimal("300.00")
    assert preview["remaining_balance"] == Decimal("1600.00")


async def test_preview_applies_a_fixed_amount_and_the_band(db: AsyncSession, tenant_ctx) -> None:
    """A fixed deposit, and a percentage clamped into the merchant's band.

    Same order amounts, two policies: the answers must differ, which is only
    true if the saved policy — not a constant — is what the engine read.
    """
    order = await _order(db, tenant_ctx.tenant_id)
    await DepositService.save_policy(
        db,
        tenant_ctx.tenant_id,
        name="Flat 500",
        deposit_type=TYPE_FIXED,
        deposit_value=Decimal("500.00"),
    )
    assert (await DepositService.preview_deposit(db, tenant_ctx.tenant_id, order.id))[
        "deposit"
    ] == Decimal("500.00")

    await DepositService.save_policy(
        db,
        tenant_ctx.tenant_id,
        name="Half the order, capped",
        deposit_type=TYPE_PERCENTAGE,
        deposit_value=Decimal("50"),
        maximum_deposit=Decimal("500.00"),
    )
    # 50% of 2,100 = 1,050 -> clamped to the merchant's 500 ceiling.
    clamped = await DepositService.preview_deposit(db, tenant_ctx.tenant_id, order.id)
    assert clamped["deposit"] == Decimal("500.00")
    assert clamped["policy_version"] == 2


async def test_no_active_policy_prices_no_deposit(db: AsyncSession, tenant_ctx) -> None:
    """Zero with ``policy_version=None`` — never an invented default.

    A shop that has never configured a deposit must not be charged one by a
    fallback constant, and the answer must SAY that no policy was involved.
    """
    order = await _order(db, tenant_ctx.tenant_id)

    preview = await DepositService.preview_deposit(db, tenant_ctx.tenant_id, order.id)
    assert preview["deposit"] == Decimal("0.00")
    assert preview["policy_version"] is None
    assert preview["remaining_balance"] == Decimal(GRAND_TOTAL)


async def test_a_none_policy_collects_nothing_but_is_still_a_version(
    db: AsyncSession, tenant_ctx
) -> None:
    order = await _order(db, tenant_ctx.tenant_id)
    await DepositService.save_policy(
        db,
        tenant_ctx.tenant_id,
        name="No deposits",
        deposit_type=TYPE_NONE,
        deposit_value=Decimal("0"),
    )

    preview = await DepositService.preview_deposit(db, tenant_ctx.tenant_id, order.id)
    assert preview["deposit"] == Decimal("0.00")
    assert preview["policy_version"] == 1, "an explicit 'none' IS a decision, unlike no policy"


async def test_a_superseded_version_never_moves_the_answer(db: AsyncSession, tenant_ctx) -> None:
    """Version semantics, pinned — NOT an order snapshot.

    ``preview_deposit`` names the policy version it priced against and always
    reads the ACTIVE row, so editing a superseded row must change nothing. The
    number a CUSTOMER was already told is a different fact and lives on the
    order, persisted at checkout — that snapshot is the next increment and is
    deliberately not asserted here, because a preview cannot provide it.
    """
    order = await _order(db, tenant_ctx.tenant_id)
    first = await DepositService.save_policy(
        db,
        tenant_ctx.tenant_id,
        name="Standard 20%",
        deposit_type=TYPE_PERCENTAGE,
        deposit_value=Decimal("20"),
    )
    before = await DepositService.preview_deposit(db, tenant_ctx.tenant_id, order.id)
    assert before["deposit"] == Decimal("420.00") and before["policy_version"] == 1

    await DepositService.save_policy(
        db,
        tenant_ctx.tenant_id,
        name="Standard 25%",
        deposit_type=TYPE_PERCENTAGE,
        deposit_value=Decimal("25"),
    )
    # The superseded version is edited directly, the way a data fix would be.
    stale = await db.get(DepositPolicy, first.id)
    assert stale is not None
    stale.deposit_value = Decimal("99")
    stale.name = "Rewritten after the fact"
    await db.flush()

    after = await DepositService.preview_deposit(db, tenant_ctx.tenant_id, order.id)
    assert after["policy_version"] == 2
    assert after["deposit"] == Decimal("525.00"), "the active version is the only one priced"
    assert after["remaining_balance"] == Decimal("2100.00")

    # And the ORDER's own money is the same rows it always was: a policy edit
    # re-reads the order, it never re-prices it.
    await db.refresh(order)
    assert order.grand_total == Decimal(GRAND_TOTAL)
    assert order.subtotal == Decimal("2000.00")


async def test_preview_reads_the_order_row_a_second_time_not_the_first_answer(
    db: AsyncSession, tenant_ctx
) -> None:
    """A repeat call re-reads the stored amounts; it is not a cached answer.

    The engine is a pure function over stored amounts, so a repeat call must be
    idempotent — anything else means a second source of truth for the figure.
    The order row is then CHANGED and the preview must follow it: a version that
    memoised its first answer would sail through the idempotence assertion above
    and fail this one.
    """
    order = await _order(db, tenant_ctx.tenant_id)
    await DepositService.save_policy(
        db,
        tenant_ctx.tenant_id,
        name="Standard 20%",
        deposit_type=TYPE_PERCENTAGE,
        deposit_value=Decimal("20"),
    )
    once = await DepositService.preview_deposit(db, tenant_ctx.tenant_id, order.id)
    twice = await DepositService.preview_deposit(db, tenant_ctx.tenant_id, order.id)
    assert once == twice

    order.grand_total = Decimal("1000.00")
    order.subtotal = Decimal("900.00")
    await db.flush()
    after = await DepositService.preview_deposit(db, tenant_ctx.tenant_id, order.id)
    assert after["deposit"] == Decimal("200.00"), "the preview must re-read the order row"


async def test_preview_refuses_another_tenants_order(db: AsyncSession, tenant_ctx) -> None:
    """Not-found, not zero: "no policy" and "not your order" are different facts."""
    order = await _order(db, tenant_ctx.tenant_id)
    await DepositService.save_policy(
        db,
        tenant_ctx.tenant_id,
        name="Standard 20%",
        deposit_type=TYPE_PERCENTAGE,
        deposit_value=Decimal("20"),
    )

    other_id = await _foreign_tenant(db)
    await bind_tenant(db, other_id)
    with pytest.raises(NotFoundError):
        await DepositService.preview_deposit(db, other_id, order.id)
    with pytest.raises(NotFoundError):
        await DepositService.preview_deposit(db, other_id, uuid.uuid4())


async def test_preview_follows_the_order_currency_not_the_tenant_default(
    db: AsyncSession, tenant_ctx
) -> None:
    """The deposit is quoted in the currency the ORDER is owed in (§47).

    A JPY order in an EGP shop is priced in yen, because the customer's bill is
    in yen; the two-decimal column is what a policy is stored in, not what the
    answer is rounded to.
    """
    order = await _order(
        db,
        tenant_ctx.tenant_id,
        subtotal="2000",
        shipping_total="100",
        grand_total="2100",
        currency="JPY",
    )
    await DepositService.save_policy(
        db,
        tenant_ctx.tenant_id,
        name="Standard 20%",
        deposit_type=TYPE_PERCENTAGE,
        deposit_value=Decimal("20"),
    )

    preview = await DepositService.preview_deposit(db, tenant_ctx.tenant_id, order.id)
    assert preview["currency"] == "JPY"
    assert preview["deposit"] == Decimal("420")


# ------------------------------------------------------------------- HTTP ----


USER_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")


def _client(
    db: AsyncSession, tenant_id: uuid.UUID, permissions: set[str], *, user_id: uuid.UUID = USER_ID
) -> AsyncClient:
    """A DB-backed client over the real app: the routes run, and the rows they
    touch are the test transaction's own.

    Same harness ``tests/test_customers_http_surface.py`` uses — the real app
    with auth and tenancy swapped, nothing else stubbed. The two middlewares that
    open their own Redis connection come off, so a request stays on the test
    session instead of reaching for infrastructure a unit run has none of.
    """
    app = create_app()
    app.user_middleware = [
        m for m in app.user_middleware if m.cls not in {IdempotencyMiddleware, RateLimitMiddleware}
    ]
    app.middleware_stack = None  # force Starlette to rebuild the stack

    async def _session() -> Any:
        yield db

    ctx = TenantContext(
        session=db,
        user=AuthedUser(id=user_id, tenant_id=tenant_id, role_code="owner"),
        tenant_id=tenant_id,
        role_code="owner",
        permission_codes=set(permissions),
    )
    app.dependency_overrides[get_tenant_ctx] = lambda: ctx
    app.dependency_overrides[get_db] = _session
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test", timeout=20)


def test_the_deposit_routes_are_mounted() -> None:
    paths = create_app().openapi()["paths"]
    assert "/api/v1/orders/deposit-policies" in paths
    assert {"get", "post"} <= set(paths["/api/v1/orders/deposit-policies"])
    assert "/api/v1/orders/{order_id}/deposit" in paths


def test_the_policy_list_is_not_swallowed_by_the_order_route() -> None:
    """``/orders/{order_id}`` is registered beside ``/orders/deposit-policies``.

    FastAPI matches in registration order, so a "{order_id}" route that arrives
    first turns the list call into a 422 ("deposit-policies" is not a UUID) and
    the screen never reaches its data. The sub-routers share ONE ``APIRouter``
    (``routers/_deps.py``), so the order its ``routes`` list is in is the order
    the endpoints were decorated in — which is exactly what
    ``routers/__init__.py``'s import order decides.
    """
    routes = [r.path for r in orders_router.routes]
    list_path = "/orders/deposit-policies"
    assert list_path in routes, f"the deposit-policy route is not mounted: {routes}"
    detail_path = "/orders/{order_id}"
    assert detail_path in routes
    assert routes.index(list_path) < routes.index(detail_path), (
        "/orders/{order_id} is registered before /orders/deposit-policies — "
        "the literal path would be parsed as an order id and 422"
    )


async def test_http_save_and_list_carry_money_as_strings(db: AsyncSession, tenant_ctx) -> None:
    """§47 on the wire: a Decimal leaves as ``str(Decimal)``, exactly like ``_payment_out``.

    A JSON number would be parsed by the browser as a float, and the merchant's
    20.00 percent would arrive as 20 with no scale at all.
    """
    async with _client(
        db,
        tenant_ctx.tenant_id,
        {"orders:read", "settings:read", "settings:write"},
        user_id=tenant_ctx.user.id,
    ) as client:
        created = await client.post(
            f"{API}/deposit-policies",
            json={
                "name": "Standard 20%",
                "deposit_type": "percentage",
                "deposit_value": "20",
                "calculation_base": "grand_total",
                "minimum_deposit": "50.00",
                "maximum_deposit": "5000.00",
            },
        )
        assert created.status_code == 201, created.text
        body = created.json()
        assert body["version"] == 1
        assert body["is_active"] is True
        assert body["deposit_value"] == "20.00"
        assert body["minimum_deposit"] == "50.00"
        assert body["maximum_deposit"] == "5000.00"
        assert body["currency"] == "EGP"

        listed = await client.get(f"{API}/deposit-policies")
        assert listed.status_code == 200, listed.text
        rows = listed.json()
        assert [r["version"] for r in rows] == [1]
        assert rows[0]["name"] == "Standard 20%"


async def test_http_deposit_preview_of_one_order(db: AsyncSession, tenant_ctx) -> None:
    order = await _order(db, tenant_ctx.tenant_id)
    await DepositService.save_policy(
        db,
        tenant_ctx.tenant_id,
        name="Standard 20%",
        deposit_type=TYPE_PERCENTAGE,
        deposit_value=Decimal("20"),
    )

    async with _client(db, tenant_ctx.tenant_id, {"orders:read"}) as client:
        response = await client.get(f"{API}/{order.id}/deposit")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["deposit"] == "420.00"
    assert body["remaining_balance"] == "2100.00"  # nothing paid yet
    assert body["policy_version"] == 1
    assert body["currency"] == "EGP"
    assert body["grand_total"] == "2100.00"


async def test_http_rejects_an_invalid_policy_with_the_engines_words(
    db: AsyncSession, tenant_ctx
) -> None:
    """The refusal reason survives the trip to the client — the merchant reads
    WHY, not just that the save failed."""
    async with _client(db, tenant_ctx.tenant_id, {"settings:write"}) as client:
        response = await client.post(
            f"{API}/deposit-policies",
            json={
                "name": "Impossible",
                "deposit_type": "percentage",
                "deposit_value": "150",
            },
        )
    assert response.status_code == 400, response.text
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert "cannot exceed 100" in error["message"]
    assert await _policy_count(db, tenant_ctx.tenant_id) == 0


async def test_http_never_takes_amounts_from_the_client(db: AsyncSession, tenant_ctx) -> None:
    """The closed request model is the guard.

    A deposit policy is a RULE about the merchant's own money; an order preview
    takes only an id. If either accepted an amount, the customer's browser would
    be deciding what it owes — the exact thing §6.3 forbids.
    """
    paths = create_app().openapi()["paths"]
    post_body = paths["/api/v1/orders/deposit-policies"]["post"]
    schema_ref = post_body["requestBody"]["content"]["application/json"]["schema"]["$ref"]
    schema_name = schema_ref.rsplit("/", 1)[-1]
    schemas = create_app().openapi()["components"]["schemas"]
    fields = set(schemas[schema_name]["properties"])
    assert fields == {
        "name",
        "deposit_type",
        "deposit_value",
        "calculation_base",
        "minimum_deposit",
        "maximum_deposit",
    }, f"the policy request must carry no money of its own: {sorted(fields)}"

    preview_path = paths["/api/v1/orders/{order_id}/deposit"]["get"]
    assert "requestBody" not in preview_path, "a preview must not accept a body"
    # Only the caller's own position in the path/query space; the tenant,
    # workspace and authorization headers the auth dependency declares are the
    # framework's, not this route's inputs.
    preview_params = {p["name"] for p in preview_path["parameters"] if p["in"] in ("path", "query")}
    assert preview_params == {"order_id"}, (
        f"the preview takes only the order id, got {sorted(preview_params)}"
    )


async def test_a_caller_without_the_permission_is_refused(db: AsyncSession, tenant_ctx) -> None:
    async with _client(db, tenant_ctx.tenant_id, {"orders:read"}) as client:
        denied = await client.post(
            f"{API}/deposit-policies",
            json={"name": "Nope", "deposit_type": "none", "deposit_value": "0"},
        )
    assert denied.status_code in (401, 403), denied.text


# ------------------------------------------------------- review-round fixes ----


async def test_selling_is_not_enough_to_rewrite_the_money_policy(
    db: AsyncSession, tenant_ctx
) -> None:
    """`orders:write` lets staff fulfil orders; it must not rewrite pricing rules.

    The provisioned role matrix already says this out loud: `manager` is granted
    every resource EXCEPT `settings:write` and `billing:write`, because changing
    how money is collected is an owner act. A deposit rule is exactly that act,
    so the write endpoint is gated on `settings:write`, not `orders:write`.
    """
    async with _client(db, tenant_ctx.tenant_id, {"orders:write"}) as client:
        denied = await client.post(
            f"{API}/deposit-policies",
            json={"name": "Free of charge", "deposit_type": "none", "deposit_value": "0"},
        )
    assert denied.status_code in (401, 403), denied.text
    assert await DepositService.get_active(db, tenant_ctx.tenant_id) is None


async def test_percentage_precision_does_not_follow_currency(db, tenant_ctx):
    tenant_ctx.tenant.currency = "JPY"
    await db.flush()
    policy = await DepositService.save_policy(
        db,
        tenant_ctx.tenant_id,
        name="Fractional rate",
        deposit_type=TYPE_PERCENTAGE,
        deposit_value="20.50",
    )
    await db.refresh(policy)
    assert policy.deposit_value == Decimal("20.50")
    order = await _order(db, tenant_ctx.tenant_id, currency="JPY")
    preview = await DepositService.preview_deposit(db, tenant_ctx.tenant_id, order.id)
    assert preview["deposit"] == Decimal("431")


async def test_repeated_unchanged_save_does_not_append_a_version(db, tenant_ctx):
    kwargs = {"name": "Standard", "deposit_type": TYPE_PERCENTAGE, "deposit_value": "20"}
    first = await DepositService.save_policy(db, tenant_ctx.tenant_id, **kwargs)
    second = await DepositService.save_policy(db, tenant_ctx.tenant_id, **kwargs)
    assert first.id == second.id
    assert await _policy_count(db, tenant_ctx.tenant_id) == 1


@pytest.mark.parametrize(
    "field,value", [("deposit_value", "20.001"), ("minimum_deposit", "-0.001")]
)
async def test_invalid_precision_and_negative_values_are_not_rounded_away(
    db, tenant_ctx, field, value
):
    kwargs = {"name": "Invalid", "deposit_type": TYPE_PERCENTAGE, "deposit_value": "20"}
    kwargs[field] = value
    with pytest.raises(ValidationError):
        await DepositService.save_policy(db, tenant_ctx.tenant_id, **kwargs)
    assert await _policy_count(db, tenant_ctx.tenant_id) == 0


async def test_policy_change_records_audit_and_outbox(db, tenant_ctx):
    policy = await DepositService.save_policy(
        db,
        tenant_ctx.tenant_id,
        name="Audited",
        deposit_type=TYPE_PERCENTAGE,
        deposit_value="20",
        actor_user_id=tenant_ctx.user.id,
    )
    audit = (
        await db.execute(
            text("SELECT actor_user_id, after FROM audit_logs WHERE resource_id = :id"),
            {"id": str(policy.id)},
        )
    ).one()
    assert audit.actor_user_id == tenant_ctx.user.id
    assert audit.after["deposit_value"] == "20.00"
    event = (
        await db.execute(
            text("SELECT payload FROM outbox_events WHERE aggregate_id = :id"), {"id": policy.id}
        )
    ).scalar_one()
    assert event["event_type"] == "order.deposit_policy_changed"
    assert event["version"] == 1


async def test_deposit_reads_require_their_own_permissions(db, tenant_ctx):
    order = await _order(db, tenant_ctx.tenant_id)
    async with _client(db, tenant_ctx.tenant_id, set()) as client:
        assert (await client.get(f"{API}/deposit-policies")).status_code == 403
        assert (await client.get(f"{API}/{order.id}/deposit")).status_code == 403


async def test_a_fixed_deposit_in_another_currency_is_refused_not_reinterpreted(
    db: AsyncSession, tenant_ctx
) -> None:
    """150 EGP of deposit on a JPY order is not 150 yen.

    The policy is written in the tenant's money and a FIXED amount is an amount
    of that money. Silently reading the same digits as the order's currency
    would charge the customer an unannounced sum, so the preview refuses and
    names the two currencies instead of producing a plausible-looking number.
    A percentage-only policy has no absolute money in it and stays safe, which
    is what the JPY test above proves.
    """
    order = await _order(db, tenant_ctx.tenant_id, currency="JPY")
    await DepositService.save_policy(
        db,
        tenant_ctx.tenant_id,
        name="Flat deposit",
        deposit_type=TYPE_FIXED,
        deposit_value=Decimal("150"),
    )
    with pytest.raises(ValidationError, match="EGP"):
        await DepositService.preview_deposit(db, tenant_ctx.tenant_id, order.id)


async def test_a_percentage_band_in_another_currency_is_also_refused(
    db: AsyncSession, tenant_ctx
) -> None:
    """The minimum and maximum are amounts of the POLICY's money, too.

    A 20% rule is currency-free, but a "minimum 100" attached to it is not: that
    band is an amount the merchant typed in their own currency, so letting it
    slide into another currency is the same reinterpretation as a fixed amount.
    """
    order = await _order(db, tenant_ctx.tenant_id, currency="JPY")
    await DepositService.save_policy(
        db,
        tenant_ctx.tenant_id,
        name="20% with a floor",
        deposit_type=TYPE_PERCENTAGE,
        deposit_value=Decimal("20"),
        minimum_deposit=Decimal("100"),
    )
    with pytest.raises(ValidationError, match="EGP"):
        await DepositService.preview_deposit(db, tenant_ctx.tenant_id, order.id)


async def test_policy_amounts_are_closed_at_the_tenants_own_scale(
    db: AsyncSession, tenant_ctx
) -> None:
    """A zero-exponent currency cannot store half a unit.

    ``save_policy`` used to close every amount at two places, so a JPY shop's
    fixed 100.50 was stored and echoed as 100.50 and then charged as 101. The
    value the merchant is shown is now the value the customer is charged: the
    amount is closed at the TENANT's currency exponent, once, on the way in.
    """
    tenant = await db.get(Tenant, tenant_ctx.tenant_id)
    assert tenant is not None
    tenant.currency = "JPY"
    await db.flush()

    order = await _order(
        db,
        tenant_ctx.tenant_id,
        subtotal="400",
        shipping_total="100",
        grand_total="500",
        currency="JPY",
    )
    policy = await DepositService.save_policy(
        db,
        tenant_ctx.tenant_id,
        name="Flat deposit",
        deposit_type=TYPE_FIXED,
        deposit_value=Decimal("100.50"),
    )
    assert policy.deposit_value == Decimal("101")

    preview = await DepositService.preview_deposit(db, tenant_ctx.tenant_id, order.id)
    assert preview["deposit"] == Decimal("101")
    # A preview means "nothing collected yet", so the balance is the whole rest
    # of the order, not the total minus the deposit just computed. The worker
    # that records a real capture passes the paid amount to the same function.
    assert preview["remaining_balance"] == Decimal("500")


async def test_two_versions_cannot_share_one_number(db: AsyncSession, tenant_ctx) -> None:
    """A version is an identity, not a hint.

    The active-row index only stops two ACTIVE rows. Without a second constraint
    two concurrent saves can both compute max(version)+1 and commit different
    rules under the SAME version number, which makes `policy_version=2` an
    ambiguous citation. The constraint is asserted the only way that counts —
    writing the duplicate directly, with no service in the way.
    """
    await DepositService.save_policy(
        db,
        tenant_ctx.tenant_id,
        name="Standard 20%",
        deposit_type=TYPE_PERCENTAGE,
        deposit_value=Decimal("20"),
    )
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            db.add(
                DepositPolicy(
                    tenant_id=tenant_ctx.tenant_id,
                    name="A different rule wearing the same version",
                    version=1,
                    is_active=False,
                    deposit_type=TYPE_FIXED,
                    deposit_value=Decimal("100.00"),
                    currency="EGP",
                    calculation_base=BASE_GRAND_TOTAL,
                )
            )
            await db.flush()


async def test_an_amount_beyond_the_application_limit_is_a_validation_error(
    db: AsyncSession, tenant_ctx
) -> None:
    """Policy input uses the same cap as manually entered order money."""
    with pytest.raises(ValidationError):
        await DepositService.save_policy(
            db,
            tenant_ctx.tenant_id,
            name="Absurd deposit",
            deposit_type=TYPE_FIXED,
            deposit_value=Decimal("1000000000"),
        )
    assert await DepositService.get_active(db, tenant_ctx.tenant_id) is None


async def test_a_nan_amount_is_a_validation_error_not_a_crash(db: AsyncSession, tenant_ctx) -> None:
    """NaN and Infinity cannot be stored, and Decimal comparisons on them raise.

    The service converts arithmetic failures into the same ValidationError the
    engine's refusals produce, rather than leaking InvalidOperation out as a 500.
    """
    for bad in (Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity")):
        with pytest.raises(ValidationError):
            await DepositService.save_policy(
                db,
                tenant_ctx.tenant_id,
                name="Not a number",
                deposit_type=TYPE_FIXED,
                deposit_value=bad,
            )
    assert await DepositService.get_active(db, tenant_ctx.tenant_id) is None
