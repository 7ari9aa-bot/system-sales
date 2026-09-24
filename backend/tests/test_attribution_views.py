"""M5 / §167 — attribution models are alternative VIEWS, never addends.

§167 ("METRIC DEFINITIONS", docs/spec/ARCHITECTURE_PATCH_125-177.txt:1994) is the
section that owns this: one metric, one definition, carrying its own ``source``,
so that Revenue/ROAS/conversion cannot be computed differently per surface. It
does NOT ask for a conversion to be credited to two models at once and then both
figures to be additive. first-touch and last-touch each credit 100% of the order
(by definition); linear/time-decay/position-based split it. Two such views of the
same 200.00 order are 200.00 of money, not 400.00 — so nothing in the payload may
ever present 400.00.

These tests pin: an additive decomposition sums to EXACTLY the order value
(no float drift, no rounding surplus), one canonical money figure per report, and
a DB constraint so the same touchpoint cannot be credited twice under one model.
"""

from __future__ import annotations

import uuid
from decimal import Decimal, InvalidOperation

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.customers.models import Customer
from app.modules.marketing.attribution_service import AttributionService
from app.modules.marketing.models import Attribution
from app.modules.marketing.service import MarketingService


def _numbers(payload: object) -> list[float]:
    """Every AMOUNT reachable in a JSON-shaped payload — the summing hazard.

    ADR-001/§47 moves money across the boundary as a Decimal STRING, so a guard
    that walked only ``int``/``float`` would stop seeing the money the moment the
    wire changed shape and would pass vacuously. Numeric strings are parsed
    through Decimal (never a bare ``float()``) and collected alongside the
    numbers, so "nothing in the payload is 400.00" means the same thing on either
    wire.
    """
    if isinstance(payload, dict):
        return [v for kv in payload.values() for v in _numbers(kv)]
    if isinstance(payload, list):
        return [v for item in payload for v in _numbers(item)]
    if isinstance(payload, bool):
        return []
    if isinstance(payload, (int, float)):
        return [float(payload)]
    if isinstance(payload, str):
        try:
            return [float(Decimal(payload))]
        except InvalidOperation:
            return []
    return []


# ---------------------------------------------------------------------------
# 1. The split is exact (DB-free)
# ---------------------------------------------------------------------------


def test_a_multi_touch_split_distributes_the_value_without_losing_or_inventing_pence() -> None:
    weights = AttributionService.compute_weights(3, "linear")
    parts = AttributionService.split_credited_value(Decimal("100.01"), weights)

    assert len(parts) == 3
    assert sum(parts, Decimal("0.00")) == Decimal("100.01")
    assert all(p >= 0 for p in parts)


def test_a_single_touch_model_credits_the_whole_value_exactly_once() -> None:
    weights = AttributionService.compute_weights(2, "last_touch")
    parts = AttributionService.split_credited_value(Decimal("200.00"), weights)

    assert sum(parts, Decimal("0.00")) == Decimal("200.00")
    assert parts[-1] == Decimal("200.00")
    assert parts[0] == Decimal("0.00")


def test_position_based_shares_sum_to_one_and_never_above_the_order() -> None:
    weights = AttributionService.compute_weights(4, "position_based")
    assert sum(weights) == pytest.approx(1.0)
    parts = AttributionService.split_credited_value(Decimal("333.33"), weights)
    assert sum(parts, Decimal("0.00")) == Decimal("333.33")


def test_the_weights_of_every_model_partition_one_order() -> None:
    for model in ("first_touch", "last_touch", "linear", "time_decay", "position_based"):
        weights = AttributionService.compute_weights(5, model)
        assert sum(weights) == pytest.approx(1.0), model


# ---------------------------------------------------------------------------
# 2. The report shape is not summable (DB-free)
# ---------------------------------------------------------------------------


def test_a_report_of_two_full_credit_views_never_adds_up_above_the_order() -> None:
    report = AttributionService.attribution_report(
        campaign_id=uuid.uuid4(),
        days=30,
        model_rows=[
            ("first_touch", 1, Decimal("200.00")),
            ("last_touch", 1, Decimal("200.00")),
        ],
    )

    # One canonical number, from one model — that is what analytics quotes.
    assert report["canonical_model"] == "last_touch"
    # An AMOUNT, so a Decimal string across the wire (ADR-001/§47), not a float64
    # a client has to trust its JSON parser to reproduce. This assertion used to
    # read `== pytest.approx(200.0)`, which pinned the bug rather than the money.
    assert report["revenue"] == "200.00"
    assert Decimal(report["revenue"]) == Decimal("200.00")
    assert report["conversions"] == 1
    # Each model is a labelled view of the SAME money, and says so.
    assert report["views_are_alternative"] is True
    assert {v["model"] for v in report["alternative_views"]} == {"first_touch", "last_touch"}
    assert all(v["never_sum_with_other_views"] is True for v in report["alternative_views"])
    # Nothing in the payload is 400: the two views cannot both be counted.
    assert 400.0 not in _numbers(report)
    assert max(_numbers(report)) <= 200.0


def test_a_report_without_attributions_reports_zero_not_absent() -> None:
    report = AttributionService.attribution_report(
        campaign_id=uuid.uuid4(), days=30, model_rows=[]
    )
    # Zero of money is still an amount: "0.00", the shape every other credit in
    # this payload carries. It was `== 0`, which asserted the float wire.
    assert report["revenue"] == "0.00"
    assert report["alternative_views"] == []


def test_the_summing_guard_still_sees_money_written_as_a_string() -> None:
    """A guard that stops working when the wire changes shape is worse than none.

    §47/ADR-001 moves marketing AMOUNTS onto Decimal strings, and
    ``attribution_service.attribution_report`` ships ``revenue`` and
    ``credited_revenue`` that way now — which is precisely the moment a
    numeric-only guard would have gone blind. This pins that ``_numbers`` reads
    the same money whichever way it is serialised, so "nothing here is 400.00"
    cannot be satisfied by a payload that merely stopped looking like numbers.
    """
    as_string = {
        "revenue": "200.00",
        "alternative_views": [{"credited_revenue": "200.00", "model": "first_touch"}],
    }
    as_number = {"revenue": 200.0, "alternative_views": [{"credited_revenue": 200.0}]}

    assert _numbers(as_string) == _numbers(as_number) == [200.0, 200.0]
    assert 400.0 not in _numbers(as_string)
    # A label is not an amount: a currency code and a day name stay out.
    assert _numbers({"currency": "EGP", "day": "2026-03-15"}) == []
    # A count is not money, but it is still a number the guard can see.
    assert _numbers({"views_are_alternative": True, "orders_count": 3}) == [3.0]


def test_the_last_touch_view_of_a_split_is_canonical_when_only_a_split_exists() -> None:
    """A tenant that computed linear only still gets one honest number."""
    report = AttributionService.attribution_report(
        campaign_id=uuid.uuid4(),
        days=30,
        model_rows=[("linear", 2, Decimal("90.00"))],
    )
    assert report["canonical_model"] == "linear"
    assert report["revenue"] == "90.00"


# ---------------------------------------------------------------------------
# 3. Live rows and the DB guarantee (CI Postgres)
# ---------------------------------------------------------------------------


async def _seed_two_touch_conversion(
    db: AsyncSession, tenant_id: uuid.UUID, *, campaign_name: str = "Attrib Camp"
) -> dict:
    campaign = await MarketingService.create_campaign(
        db, tenant_id, name=campaign_name, provider="facebook"
    )
    customer = Customer(tenant_id=tenant_id, name="Viewed Customer")
    db.add(customer)
    await db.flush()
    await MarketingService.record_touchpoint(
        db, tenant_id, customer_id=customer.id, source="facebook", campaign_id=campaign.id
    )
    await MarketingService.record_touchpoint(
        db, tenant_id, customer_id=customer.id, source="google", campaign_id=campaign.id
    )
    conversion = await MarketingService.record_conversion(
        db, tenant_id, customer_id=customer.id, value=200
    )
    await db.flush()
    return {"campaign": campaign, "customer": customer, "conversion": conversion}


async def test_the_campaign_rollup_quotes_one_canonical_figure(
    db: AsyncSession, tenant_ctx
) -> None:
    seeded = await _seed_two_touch_conversion(db, tenant_ctx.tenant_id)
    report = await AttributionService.get_campaign_attribution(
        db, tenant_ctx.tenant_id, seeded["campaign"].id
    )

    assert report["revenue"] == "200.00"
    assert {v["model"] for v in report["alternative_views"]} == {"first_touch", "last_touch"}
    assert report["views_are_alternative"] is True
    assert 400.0 not in _numbers(report)


async def test_within_one_model_a_conversions_credits_sum_to_its_value(
    db: AsyncSession, tenant_ctx
) -> None:
    seeded = await _seed_two_touch_conversion(
        db, tenant_ctx.tenant_id, campaign_name="Partition Check"
    )
    rows = (
        await db.execute(
            select(Attribution.model, func.sum(Attribution.credited_value))
            .where(
                Attribution.tenant_id == tenant_ctx.tenant_id,
                Attribution.conversion_id == seeded["conversion"].id,
            )
            .group_by(Attribution.model)
        )
    ).all()

    assert rows, "expected attribution rows for the conversion"
    for model, credited in rows:
        assert float(credited) == pytest.approx(200.0), model


async def test_recomputing_a_model_stacks_no_second_credit(
    db: AsyncSession, tenant_ctx
) -> None:
    seeded = await _seed_two_touch_conversion(
        db, tenant_ctx.tenant_id, campaign_name="Recompute Check"
    )
    first = await AttributionService.compute_for_conversion(
        db, tenant_ctx.tenant_id, seeded["conversion"].id, model="linear"
    )
    await db.flush()
    assert first

    again = await AttributionService.compute_for_conversion(
        db, tenant_ctx.tenant_id, seeded["conversion"].id, model="linear"
    )
    await db.flush()

    assert again == []
    total = (
        await db.execute(
            select(func.count())
            .select_from(Attribution)
            .where(
                Attribution.tenant_id == tenant_ctx.tenant_id,
                Attribution.conversion_id == seeded["conversion"].id,
                Attribution.model == "linear",
            )
        )
    ).scalar_one()
    assert total == len(first)


async def test_the_database_refuses_a_duplicate_credit_row(
    db: AsyncSession, tenant_ctx
) -> None:
    """A SELECT-then-INSERT guard races; the constraint is the guarantee."""
    seeded = await _seed_two_touch_conversion(
        db, tenant_ctx.tenant_id, campaign_name="Constraint Check"
    )
    existing = (
        await db.execute(
            select(Attribution).where(
                Attribution.tenant_id == tenant_ctx.tenant_id,
                Attribution.conversion_id == seeded["conversion"].id,
                Attribution.model == "last_touch",
            )
        )
    ).scalars().one()

    async with db.begin_nested():
        db.add(
            Attribution(
                tenant_id=tenant_ctx.tenant_id,
                conversion_id=existing.conversion_id,
                touchpoint_id=existing.touchpoint_id,
                model="last_touch",
                weight=1,
                credited_value=Decimal("200.00"),
            )
        )
        with pytest.raises(IntegrityError):
            await db.flush()
