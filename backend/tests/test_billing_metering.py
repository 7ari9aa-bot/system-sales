"""Spec §53–54 — billing period metering and IMMUTABLE period snapshots.

The audit found `BillingSnapshotService` sitting in billing/service.py with NO
CALLER AT ALL: no router imported it, no service called it, no test touched it.
It was dead code, and its `close_period` was wrong in three ways — it summed
`UsageRecord.quantity` through `float()`, it never looked at `ai_usage` (the
only place AI usage is actually written), and it stored the period inside the
`extra` JSONB blob where nothing could constrain it, so "immutable" was a
convention with no enforcement behind it.

Two properties are pinned here, and they need different tests:

* **A closed period never changes** (§54) — a usage record arriving late must
  not move an invoice already issued.
* **Closed periods never overlap** — `[Aug 1, Sep 1)` and `[Aug 15, Sep 15)`
  would bill the shared days twice. The unique constraint does NOT catch this
  (the triples differ); a tenant-scoped advisory lock plus an overlap query
  does. `test_concurrent_overlapping_closes_cannot_both_succeed` is what proves
  the lock is doing the work rather than a lucky interleaving.

Several tests deliberately BYPASS `close_period` and insert rows directly. The
service pre-checks fire first on the ordinary path, so a test that only calls
the service would still pass with the database constraint dropped — it would
pin the check, not the guarantee.

The DB-free tests run anywhere; the `db`/`tenant_ctx` ones need a database and
skip locally.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.db import bind_tenant
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.main import create_app
from app.modules.billing.models import Invoice, UsageRecord
from app.modules.billing.router import (
    ClosePeriodRequest,
    close_billing_period,
    get_billing_snapshot,
)
from app.modules.billing.service import (
    BillingSnapshotService,
    PeriodUsage,
    _as_decimal,
    _quantize_money,
)
from app.modules.identity.deps import TenantContext
from app.modules.identity.models import Tenant

PERIOD_START = date(2026, 8, 1)
PERIOD_END = date(2026, 9, 1)
NEXT_PERIOD_END = date(2026, 10, 1)


def _feature_totals(invoice: Invoice) -> dict[str, str]:
    """The frozen per-feature lines, exactly as stored in the snapshot."""
    return {
        line["feature"]: line["quantity"]
        for line in (invoice.extra or {}).get("snapshot", [])
    }


async def _record_usage_on(
    db: AsyncSession, tenant_id: uuid.UUID, feature: str, quantity: str, on: date
) -> None:
    """Append a metering row stamped with a specific date.

    `BillingService.record_usage` always stamps TODAY, so a period in the past
    cannot be populated through it — the late-arrival test needs an explicit
    date to place a row inside an already-closed period.
    """
    db.add(
        UsageRecord(
            tenant_id=tenant_id,
            feature=feature,
            quantity=Decimal(quantity),
            period_date=on,
        )
    )
    await db.flush()


async def _record_ai_usage(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    tokens_in: int,
    tokens_out: int,
    cost: str,
    on: date,
) -> None:
    """Insert an `ai_usage` row with raw SQL.

    Raw SQL rather than `app.modules.ai.models`: billing deliberately does not
    import that module (see `BillingSnapshotService.aggregate_period`), and the
    test should exercise the same access path the service uses.
    """
    await db.execute(
        text(
            "INSERT INTO ai_usage "
            "(id, tenant_id, period_date, tokens_in, tokens_out, cost, model_calls) "
            "VALUES (:id, :tenant_id, :period_date, :tokens_in, :tokens_out, "
            ":cost, 1)"
        ),
        {
            # UUID objects, not str(): a `uuid` column takes the native codec
            # input, so the test binds exactly what the service binds.
            "id": uuid.uuid4(),
            "tenant_id": tenant_id,
            "period_date": on,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "cost": Decimal(cost),
        },
    )
    await db.flush()


def _direct_invoice(tenant_id: uuid.UUID, number: str, start: date, end: date) -> Invoice:
    """An Invoice built without going through the service — for constraint tests."""
    return Invoice(
        tenant_id=tenant_id,
        number=number,
        status="open",
        subtotal=Decimal("0.00"),
        tax=Decimal("0.00"),
        total=Decimal("0.00"),
        currency="EGP",
        period_start=start,
        period_end=end,
        extra={},
    )


# ------------------------------------------------- wiring: not dead code ---


def test_the_period_routes_are_mounted() -> None:
    """The service was DEAD CODE — nothing called it, so pin the routes."""
    paths = create_app().openapi()["paths"]

    close = paths["/api/v1/billing/periods/close"]
    assert "post" in close
    assert "201" in close["post"]["responses"]

    read = paths["/api/v1/billing/periods/snapshot"]
    assert "get" in read
    assert "200" in read["get"]["responses"]


async def test_the_close_route_writes_a_snapshot_the_read_route_returns(
    db: AsyncSession, tenant_ctx
) -> None:
    """Behavioural wiring check, driving the real handlers.

    This replaces an `inspect.getsource` assertion, which pinned nothing: it
    passed even with the service body reverted, because the call text was still
    present. Calling the handlers means a route that stopped using the service
    (or a service reverted to a stub) fails here.
    """
    await _record_usage_on(db, tenant_ctx.tenant_id, "messages", "10.00", PERIOD_START)
    ctx = TenantContext(
        session=db,
        user=None,
        tenant_id=tenant_ctx.tenant_id,
        role_code="owner",
        permission_codes={"billing:write"},
    )

    written = await close_billing_period(
        ClosePeriodRequest(period_start=PERIOD_START, period_end=PERIOD_END), ctx
    )
    assert written["features"] == [{"feature": "messages", "quantity": "10.00"}]
    assert written["period_start"] == PERIOD_START.isoformat()
    assert written["period_end"] == PERIOD_END.isoformat()

    read = await get_billing_snapshot(
        ctx, period_start=PERIOD_START, period_end=PERIOD_END
    )
    assert read["invoice_id"] == written["invoice_id"]
    assert read["features"] == written["features"]


# --------------------------------------------------- pure logic (DB-free) --


@pytest.mark.parametrize(
    ("start", "end"),
    [
        (date(2026, 9, 1), date(2026, 9, 1)),  # empty
        (date(2026, 9, 1), date(2026, 8, 1)),  # inverted
    ],
)
async def test_a_bad_period_is_rejected_before_the_session_is_touched(
    start: date, end: date
) -> None:
    """A zero-length or inverted period is a 400, never a silent empty invoice.

    `session=None` is the assertion: the guard must run before any DB access,
    so a caller gets ValidationError instead of an AttributeError/500. Both the
    read path and the close path must validate up front.
    """
    for call in (
        BillingSnapshotService.aggregate_period,
        BillingSnapshotService.close_period,
    ):
        with pytest.raises(ValidationError):
            await call(
                None,  # type: ignore[arg-type] — raises before the session is used
                uuid.uuid4(),
                period_start=start,
                period_end=end,
            )


def test_quantize_money_is_half_up_not_half_even() -> None:
    """Money is exact Decimal; `round()` is banned because it goes via float."""
    assert _quantize_money(Decimal("0.005")) == Decimal("0.01")
    assert _quantize_money(Decimal("0.025")) == Decimal("0.03")
    assert _quantize_money(Decimal("0.00123000")) == Decimal("0.00")
    assert isinstance(_quantize_money(Decimal("1.005")), Decimal)

    # The banned route, for contrast: HALF_EVEN rounds a half-cent DOWN, so an
    # invoice total can land a cent short of what the customer expects.
    assert round(Decimal("0.005"), 2) == Decimal("0.00")


def test_as_decimal_never_goes_through_binary_float() -> None:
    assert _as_decimal(None) == Decimal(0)
    assert _as_decimal(7) == Decimal(7)
    assert _as_decimal(Decimal("10.25")) == Decimal("10.25")
    # Decimal(str(x)), not Decimal(x): a float would expand to its full binary
    # mantissa and every downstream sum would carry the error.
    assert str(_as_decimal(0.1)) == "0.1"


def test_snapshot_lines_are_sorted_and_string_encoded() -> None:
    usage = PeriodUsage(
        features={
            "orders": Decimal("2.00"),
            "ai_tokens": Decimal("1200"),
            "messages": Decimal("10.50"),
        },
        ai_cost=Decimal("0.00123000"),
    )

    lines = BillingSnapshotService.snapshot_lines(usage)

    assert lines == [
        {"feature": "ai_tokens", "quantity": "1200"},
        {"feature": "messages", "quantity": "10.50"},
        {"feature": "orders", "quantity": "2.00"},
    ]
    # Strings, never JSON numbers: a JSON number decodes to an IEEE float, which
    # would degrade the Numeric(14,2) total on the way into JSONB.
    assert all(isinstance(line["quantity"], str) for line in lines)


# ------------------------------------------------- metering (DB-backed) ----


async def test_aggregation_totals_are_per_feature_and_period_bounded(
    db: AsyncSession, tenant_ctx
) -> None:
    """Per-feature sums, and the period is HALF-OPEN.

    period_end is exclusive, so consecutive periods never double-count the
    boundary day — a row on PERIOD_END belongs to the NEXT period.
    """
    tenant_id = tenant_ctx.tenant_id
    await _record_usage_on(db, tenant_id, "messages", "10.00", PERIOD_START)
    await _record_usage_on(db, tenant_id, "messages", "2.50", date(2026, 8, 15))
    await _record_usage_on(db, tenant_id, "orders", "3.00", date(2026, 8, 20))
    await _record_usage_on(db, tenant_id, "messages", "1000.00", date(2026, 7, 31))
    await _record_usage_on(db, tenant_id, "messages", "1000.00", PERIOD_END)

    usage = await BillingSnapshotService.aggregate_period(
        db, tenant_id, period_start=PERIOD_START, period_end=PERIOD_END
    )

    assert usage.features == {
        "messages": Decimal("12.50"),
        "orders": Decimal("3.00"),
    }


async def test_ai_usage_is_metered_from_its_real_source(
    db: AsyncSession, tenant_ctx
) -> None:
    """`ai_usage` is the REAL source of AI usage, so the meter must read it.

    `ai.usage.record_usage` is called from the model runtime and nothing ever
    writes a UsageRecord for AI. Metering only `usage_records` would report zero
    AI tokens for every tenant, forever — which is what the dead original did.
    """
    await _record_ai_usage(
        db,
        tenant_ctx.tenant_id,
        tokens_in=700,
        tokens_out=500,
        cost="0.00123000",
        on=PERIOD_START,
    )

    usage = await BillingSnapshotService.aggregate_period(
        db, tenant_ctx.tenant_id, period_start=PERIOD_START, period_end=PERIOD_END
    )

    assert usage.features == {"ai_tokens": Decimal("1200")}
    # Money stays exact at 8dp — never a float.
    assert usage.ai_cost == Decimal("0.00123000")


async def test_the_invoice_total_is_the_quantized_ai_cost(db: AsyncSession, tenant_ctx) -> None:
    """The only money-denominated usage is AI cost, so that is the invoice total.

    The 2dp MONEY column and the 8dp exact figure are both kept: quantizing for
    the column must not destroy the precision the snapshot exists to record.
    """
    await _record_ai_usage(
        db,
        tenant_ctx.tenant_id,
        tokens_in=700,
        tokens_out=500,
        cost="0.00500000",
        on=PERIOD_START,
    )

    invoice = await BillingSnapshotService.close_period(
        db, tenant_ctx.tenant_id, period_start=PERIOD_START, period_end=PERIOD_END
    )

    assert invoice.total == Decimal("0.01")  # HALF_UP, not 0.00
    assert invoice.subtotal == Decimal("0.01")
    assert invoice.tax == Decimal("0.00")
    assert isinstance(invoice.total, Decimal)
    assert (invoice.extra or {})["ai_cost"] == "0.00500000"
    assert _feature_totals(invoice) == {"ai_tokens": "1200"}


async def test_the_invoice_is_stamped_in_the_currency_its_cost_was_computed_in(
    db: AsyncSession, tenant_ctx
) -> None:
    """§47's label rule cuts BOTH ways: a money row carries the currency its own
    numbers are in.

    An `Invoice` here is the PLATFORM's bill to the tenant, and the only money
    this path computes is `ai_cost` — a USD figure (every AI cap and per-minute
    price in `core/config.py` is USD). `tenants.currency` is what the tenant's
    CUSTOMERS pay in and says nothing about what the tenant owes here. So this
    row must not take the tenant's trading currency, any more than it should
    have kept the old hard-coded "EGP".
    """
    await db.execute(
        text("UPDATE tenants SET currency = 'SAR' WHERE id = :t"),
        {"t": tenant_ctx.tenant_id},
    )
    await _record_ai_usage(
        db,
        tenant_ctx.tenant_id,
        tokens_in=700,
        tokens_out=500,
        cost="0.00500000",
        on=PERIOD_START,
    )

    invoice = await BillingSnapshotService.close_period(
        db, tenant_ctx.tenant_id, period_start=PERIOD_START, period_end=PERIOD_END
    )

    assert invoice.currency == "USD"
    assert invoice.total == Decimal("0.01")


# ------------------------------------------------ immutability (§54) -------


async def test_a_late_usage_record_does_not_move_a_closed_snapshot(
    db: AsyncSession, tenant_ctx
) -> None:
    """THE guarantee: a closed period is frozen forever.

    The test also proves the late record really landed. Without that, a
    silently-dropped INSERT would look identical to a correctly frozen
    snapshot and the test would pass for the wrong reason.
    """
    tenant_id = tenant_ctx.tenant_id
    await _record_usage_on(db, tenant_id, "messages", "10.00", PERIOD_START)

    invoice = await BillingSnapshotService.close_period(
        db, tenant_id, period_start=PERIOD_START, period_end=PERIOD_END
    )
    frozen_totals = _feature_totals(invoice)
    frozen_id = invoice.id
    assert frozen_totals == {"messages": "10.00"}

    # A usage record arrives late, for the period that is already closed.
    await _record_usage_on(db, tenant_id, "messages", "5.00", PERIOD_START)

    # It IS visible to a live aggregation...
    live = await BillingSnapshotService.aggregate_period(
        db, tenant_id, period_start=PERIOD_START, period_end=PERIOD_END
    )
    assert live.features["messages"] == Decimal("15.00")

    # ...and the snapshot still does not move. `expire_all()` is what makes this
    # a claim about the DATABASE rather than about the identity map: without it
    # the re-read could be served from the already-loaded object and would pass
    # even if the row had been updated underneath.
    db.expire_all()
    reread = await BillingSnapshotService.get_snapshot(
        db, tenant_id, period_start=PERIOD_START, period_end=PERIOD_END
    )
    assert reread.id == frozen_id
    assert _feature_totals(reread) == frozen_totals == {"messages": "10.00"}


async def test_closing_a_period_twice_is_refused_and_changes_nothing(
    db: AsyncSession, tenant_ctx
) -> None:
    """REFUSED, not idempotent-return.

    Idempotent-return would have to swallow the constraint violation and re-read
    the row, and it still could not tell "already closed, same inputs" apart
    from "an operator trying to recompute a closed period with corrected data" —
    which is the recompute path immutability exists to forbid. Refusing is loud
    and unambiguous; the caller can GET the existing snapshot.
    """
    tenant_id = tenant_ctx.tenant_id
    await _record_usage_on(db, tenant_id, "messages", "10.00", PERIOD_START)

    first = await BillingSnapshotService.close_period(
        db, tenant_id, period_start=PERIOD_START, period_end=PERIOD_END
    )
    first_totals = _feature_totals(first)

    # New usage for the closed period: the second close must still be refused,
    # and must not have written a second, "corrected" invoice.
    await _record_usage_on(db, tenant_id, "messages", "99.00", PERIOD_START)

    with pytest.raises(ConflictError):
        await BillingSnapshotService.close_period(
            db, tenant_id, period_start=PERIOD_START, period_end=PERIOD_END
        )

    db.expire_all()  # assert against the database, not the identity map
    snapshots = (
        (
            await db.execute(
                select(Invoice).where(
                    Invoice.tenant_id == tenant_id,
                    Invoice.period_start == PERIOD_START,
                    Invoice.period_end == PERIOD_END,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(snapshots) == 1
    assert _feature_totals(snapshots[0]) == first_totals == {"messages": "10.00"}


async def test_reading_a_period_that_was_never_closed_is_not_found(
    db: AsyncSession, tenant_ctx
) -> None:
    """A missing snapshot is a 404, never a silent zero-filled invoice."""
    with pytest.raises(NotFoundError):
        await BillingSnapshotService.get_snapshot(
            db,
            tenant_ctx.tenant_id,
            period_start=PERIOD_START,
            period_end=PERIOD_END,
        )


async def test_one_tenants_usage_never_enters_anothers_snapshot(
    db: AsyncSession, tenant_ctx
) -> None:
    """Every tenant-scoped query filters tenant_id, and RLS is not the only net."""
    other = Tenant(slug=f"t-{uuid.uuid4().hex[:10]}", name="Other Tenant")
    db.add(other)
    await db.flush()

    await _record_usage_on(db, tenant_ctx.tenant_id, "messages", "10.00", PERIOD_START)

    await bind_tenant(db, other.id)  # the tenant policy is live on usage_records
    await _record_usage_on(db, other.id, "messages", "999.00", PERIOD_START)
    other_invoice = await BillingSnapshotService.close_period(
        db, other.id, period_start=PERIOD_START, period_end=PERIOD_END
    )
    await bind_tenant(db, tenant_ctx.tenant_id)

    own_invoice = await BillingSnapshotService.close_period(
        db, tenant_ctx.tenant_id, period_start=PERIOD_START, period_end=PERIOD_END
    )

    assert _feature_totals(other_invoice) == {"messages": "999.00"}
    assert _feature_totals(own_invoice) == {"messages": "10.00"}


# ------------------------------------------------------- the constraints ---


async def test_the_unique_constraint_rejects_a_duplicate_period(
    db: AsyncSession, tenant_ctx
) -> None:
    """Pins `uq_invoices_tenant_period` ITSELF, not the service pre-check.

    `close_period`'s own "already closed?" check fires first on the ordinary
    path, so a test that only calls the service passes even with the constraint
    dropped — it pins the check, not the guarantee. This inserts a second row
    for the same period directly, so it fails if the constraint is removed.
    """
    tenant_id = tenant_ctx.tenant_id
    await _record_usage_on(db, tenant_id, "messages", "10.00", PERIOD_START)
    await BillingSnapshotService.close_period(
        db, tenant_id, period_start=PERIOD_START, period_end=PERIOD_END
    )

    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            db.add(_direct_invoice(tenant_id, "INV-DUPLICATE", PERIOD_START, PERIOD_END))
            await db.flush()


async def test_an_overlapping_period_is_refused(db: AsyncSession, tenant_ctx) -> None:
    """Every overlap shape is refused, and no second invoice is written.

    The unique constraint does NOT catch any of these (the triples all differ),
    so this is the guard that has to.
    """
    tenant_id = tenant_ctx.tenant_id
    await _record_usage_on(db, tenant_id, "messages", "10.00", PERIOD_START)
    await BillingSnapshotService.close_period(
        db, tenant_id, period_start=PERIOD_START, period_end=PERIOD_END
    )

    overlaps = [
        (date(2026, 8, 15), date(2026, 9, 15)),  # starts inside, ends after
        (date(2026, 8, 5), date(2026, 8, 20)),  # fully contained
        (date(2026, 7, 1), date(2026, 10, 1)),  # fully containing
    ]
    for start, end in overlaps:
        with pytest.raises(ConflictError):
            await BillingSnapshotService.close_period(
                db, tenant_id, period_start=start, period_end=end
            )

    db.expire_all()
    invoices = (
        (await db.execute(select(Invoice).where(Invoice.tenant_id == tenant_id)))
        .scalars()
        .all()
    )
    assert len(invoices) == 1, "a refused overlap must not have written an invoice"


async def test_adjacent_periods_do_not_overlap(db: AsyncSession, tenant_ctx) -> None:
    """Negative control: half-open periods that touch are NOT overlapping.

    `[Aug 1, Sep 1)` and `[Sep 1, Oct 1)` share no day. A naive `<=` comparison
    in the overlap predicate would refuse this, and every tenant's second month
    would be unbillable.
    """
    tenant_id = tenant_ctx.tenant_id
    first = await BillingSnapshotService.close_period(
        db, tenant_id, period_start=PERIOD_START, period_end=PERIOD_END
    )
    second = await BillingSnapshotService.close_period(
        db, tenant_id, period_start=PERIOD_END, period_end=NEXT_PERIOD_END
    )

    assert first.id != second.id


async def test_concurrent_overlapping_closes_cannot_both_succeed(db_url: str) -> None:
    """An overlapping close is refused even while the first one is uncommitted.

    This is the test the advisory lock exists for, and the interleaving is
    FORCED rather than hoped for: A closes a period and stays uncommitted, so it
    still holds the tenant's close lock; only then does B try an overlapping
    period.

    * With the lock, B parks in ``pg_advisory_xact_lock``. When A commits, B
      proceeds, sees A's invoice and is refused — one invoice in total.
    * Without the lock, B reads "no overlap" (A is invisible, being uncommitted)
      and commits a SECOND invoice, so the shared days are billed twice and
      `pytest.raises(ConflictError)` fails.

    That is the regression this pins. Simply firing two closes at once would not
    do it: with no interleaving, the second close fails on the ordinary
    sequential path and the test passes with the lock removed.
    """
    engine = create_async_engine(
        db_url, pool_pre_ping=True, connect_args={"statement_cache_size": 0}
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    tenant_id = uuid.uuid4()
    try:
        async with factory() as seed:
            async with seed.begin():
                await seed.execute(
                    text(
                        "INSERT INTO tenants (id, slug, name) "
                        "VALUES (:id, :slug, 'Billing close race')"
                    ),
                    {"id": tenant_id, "slug": f"bill-{tenant_id.hex[:12]}"},
                )

        conn_a = await engine.connect()
        conn_b = await engine.connect()
        try:
            session_a = async_sessionmaker(bind=conn_a, expire_on_commit=False)()
            session_b = async_sessionmaker(bind=conn_b, expire_on_commit=False)()

            await session_a.begin()
            await bind_tenant(session_a, tenant_id)
            await BillingSnapshotService.close_period(
                session_a, tenant_id, period_start=PERIOD_START, period_end=PERIOD_END
            )
            # Deliberately NOT committed: A holds the tenant's close lock.

            await session_b.begin()
            await bind_tenant(session_b, tenant_id)
            blocked = asyncio.create_task(
                BillingSnapshotService.close_period(
                    session_b,
                    tenant_id,
                    period_start=date(2026, 8, 15),
                    period_end=date(2026, 9, 15),
                )
            )
            # Let B get as far as it can before A releases the lock.
            await asyncio.sleep(0.5)
            await session_a.commit()

            with pytest.raises(ConflictError):
                await asyncio.wait_for(blocked, timeout=15)
            await session_b.rollback()
        finally:
            await session_a.close()
            await session_b.close()
            await conn_a.close()
            await conn_b.close()

        async with factory() as check:
            async with check.begin():
                await bind_tenant(check, tenant_id)
                written = (
                    await check.execute(
                        text("SELECT count(*) FROM invoices WHERE tenant_id = :t"),
                        {"t": tenant_id},
                    )
                ).scalar_one()
        assert written == 1, "the overlapping close wrote a second invoice"
    finally:
        async with factory() as cleanup:
            async with cleanup.begin():
                await bind_tenant(cleanup, tenant_id)
                await cleanup.execute(
                    text("DELETE FROM tenants WHERE id = :t"), {"t": tenant_id}
                )
        await engine.dispose()
