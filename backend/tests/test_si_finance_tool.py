"""`si_finance`: ONE tool for "what did the shop spend" and "what did it earn".

`si_expenses_summary` and `si_profit_summary` were two more choices for the model on every question.
They are one thin router now: `report` picks which tested read runs, the reads themselves are
untouched. This is the shop's MONEY, so the permission is the first thing pinned: both originals
required ``finance:read``, the merged tool must require exactly that, and an asker without it must
never be shown it. The "profit is shown only when every cost is known" rule is re-proven THROUGH the
merged tool, because an invented profit figure is the worst thing this assistant could say.
"""

from __future__ import annotations

import pytest

from app.core.errors import ValidationError
from app.applications.apparel.modules.ai.agents.sales_intelligence import tools as T
from app.applications.apparel.modules.ai.agents.sales_intelligence.permissions import asking_with
from app.applications.apparel.modules.ai.tools import get_tool
from tests.test_si_finance_tools import (
    _category,
    _delivered_sale,
    _expense,
    _variant,
)

pytestmark = pytest.mark.usefixtures("db")

OLD = ("si_expenses_summary", "si_profit_summary")
REPORTS = ("expenses", "profit")
_CLOCK = {"data_as_of", "computed_at"}


def _same(new, old) -> bool:
    """Equal in everything but the compute-time stamps (the originals differ on them too)."""
    if isinstance(new, dict) and isinstance(old, dict):
        return new.keys() == old.keys() and all(
            _same(new[k], old[k]) for k in new if k not in _CLOCK
        )
    if isinstance(new, list) and isinstance(old, list):
        return len(new) == len(old) and all(_same(a, b) for a, b in zip(new, old, strict=True))
    return new == old


def test_the_two_old_tools_are_replaced_by_one():
    assert "si_finance" in T.SI_TOOLS
    for name in OLD:
        assert name not in T.SI_TOOLS, f"{name} must not be offered next to si_finance"


@pytest.fixture(autouse=True)
def _the_owner_is_asking():
    """The computations below run as the shop owner would. WHO may read WHAT is proven in
    ``test_si_permissions_per_read`` (every read, every asker), so it is not repeated here."""
    with asking_with({"finance:read", "purchasing:read"}):
        yield


def test_si_finance_is_low_risk_and_its_reads_are_gated_when_they_run():
    T.register_si_tools()
    spec = get_tool("si_finance")
    assert spec is not None
    assert spec.risk_level == "LOW"


async def test_an_asker_without_finance_read_cannot_read_the_money(db, tenant_ctx):
    T.register_si_tools()
    for held in (set(), {"orders:read"}, {"inventory:read", "customers:read"}, None):
        with asking_with(held), pytest.raises(ValidationError, match="not allowed"):
            await T._si_finance(db, tenant_ctx.tenant_id, report="expenses")
        with asking_with(held), pytest.raises(ValidationError, match="not allowed"):
            await T._si_finance(db, tenant_ctx.tenant_id, report="profit")


def test_the_description_says_what_each_report_is_for():
    T.register_si_tools()
    text = get_tool("si_finance").description
    for report in REPORTS:
        assert f"{report} = " in text, f"the model is never told what report={report} is for"
    # each report says what it MEANS and when to pick it, not just its name
    for meaning in (
        "what the shop spent",
        "by category, by payment method",
        "what the shop earned after the cost of what it sold and after expenses",
    ):
        assert meaning in text, f"the description lost: {meaning!r}"
    # the rule that stops an invented profit must reach the model in words, not only in code
    assert "only when the cost of every sold item is known" in text
    assert "shows no profit figure" in text
    assert "limit" in text and "days" in text
    assert "si_metric" in text  # revenue and sales live in the other tool


def test_args_schema_rejects_an_unknown_report_and_keeps_the_old_bounds():
    with pytest.raises(Exception):  # noqa: B017 - pydantic ValidationError
        T.SIFinanceArgs(report="forecast")
    a = T.SIFinanceArgs(report="expenses")
    assert a.days == 30 and a.limit is None
    # the originals allowed up to a year, not 90 like the sales reads
    assert T.SIFinanceArgs(report="profit", days=366).days == 366
    for bad in ({"days": 0}, {"days": 367}, {"limit": 0}, {"limit": 26}):
        with pytest.raises(Exception):  # noqa: B017
            T.SIFinanceArgs(report="expenses", **bad)


async def test_expenses_default_limit_is_eight_and_the_cap_is_twenty_five(db, tenant_ctx):
    seen = {}

    async def spy(session, tenant_id, **kw):
        seen.update(kw)
        return {}

    orig = T._si_expenses_summary
    T._si_expenses_summary = spy
    try:
        await T._si_finance(db, tenant_ctx.tenant_id, report="expenses")
        assert seen["limit"] == 8
        with pytest.raises(ValidationError):
            await T._si_finance(db, tenant_ctx.tenant_id, report="expenses", limit=26)
    finally:
        T._si_expenses_summary = orig


async def test_an_unknown_report_is_refused_with_the_valid_ones(db, tenant_ctx):
    with pytest.raises((ValidationError, ValueError)) as exc:
        await T._si_finance(db, tenant_ctx.tenant_id, report="forecast")
    for report in REPORTS:
        assert report in str(exc.value)


async def _spend(db, tenant_id):
    cat = await _category(db, tenant_id)
    for i, amount in enumerate((500, 300, 200, 150, 100, 80, 60, 40, 30, 20)):
        await _expense(db, tenant_id, cat, amount, days_ago=1 + i)
    # an old one, only inside a long window
    await _expense(db, tenant_id, cat, 999, days_ago=200)


async def test_expenses_report_matches_the_old_expenses_summary(db, tenant_ctx):
    await _spend(db, tenant_ctx.tenant_id)
    new = await T._si_finance(db, tenant_ctx.tenant_id, report="expenses", days=30, limit=8)
    old = await T._si_expenses_summary(db, tenant_ctx.tenant_id, days=30, limit=8)
    assert _same(new, old)


async def test_expenses_days_and_limit_are_really_passed_through(db, tenant_ctx):
    await _spend(db, tenant_ctx.tenant_id)
    answers = {}
    for days in (30, 366):
        for limit in (3, 10):
            new = await T._si_finance(
                db, tenant_ctx.tenant_id, report="expenses", days=days, limit=limit
            )
            ref = await T._si_expenses_summary(db, tenant_ctx.tenant_id, days=days, limit=limit)
            assert _same(new, ref), f"expenses differs from the original at {days}d/{limit}"
            answers[(days, limit)] = new
    assert not _same(answers[(30, 10)], answers[(366, 10)]), "days made no difference"
    assert not _same(answers[(30, 3)], answers[(30, 10)]), "limit made no difference"


async def test_profit_report_matches_the_old_profit_summary(db, tenant_ctx):
    v = await _variant(db, tenant_ctx.tenant_id, "Shirt", cost=40)
    await _delivered_sale(db, tenant_ctx.tenant_id, [(v, 2, 200)])
    cat = await _category(db, tenant_ctx.tenant_id)
    await _expense(db, tenant_ctx.tenant_id, cat, 50)
    new = await T._si_finance(db, tenant_ctx.tenant_id, report="profit", days=30)
    old = await T._si_profit_summary(db, tenant_ctx.tenant_id, days=30)
    assert _same(new, old)


async def test_profit_days_is_really_passed_through(db, tenant_ctx):
    v = await _variant(db, tenant_ctx.tenant_id, "Shirt", cost=40)
    await _delivered_sale(db, tenant_ctx.tenant_id, [(v, 2, 200)], days_ago=2)
    await _delivered_sale(db, tenant_ctx.tenant_id, [(v, 5, 500)], days_ago=100)
    short = await T._si_finance(db, tenant_ctx.tenant_id, report="profit", days=30)
    long_ = await T._si_finance(db, tenant_ctx.tenant_id, report="profit", days=366)
    assert _same(short, await T._si_profit_summary(db, tenant_ctx.tenant_id, days=30))
    assert _same(long_, await T._si_profit_summary(db, tenant_ctx.tenant_id, days=366))
    assert not _same(short, long_), "a 30 and a 366 day window gave the same answer"


async def test_a_missing_cost_still_hides_profit_through_the_merged_tool(db, tenant_ctx):
    """Profit is shown ONLY when every sold line has a known cost. Re-proven on the registered tool,
    exactly as the runner calls it: an uncosted sale must produce no profit figure."""
    costed = await _variant(db, tenant_ctx.tenant_id, "Costed", cost=40)
    uncosted = await _variant(db, tenant_ctx.tenant_id, "Uncosted", cost=None)
    await _delivered_sale(db, tenant_ctx.tenant_id, [(costed, 1, 100), (uncosted, 1, 100)])
    T.register_si_tools()

    out = await get_tool("si_finance").handler(db, tenant_ctx.tenant_id, report="profit", days=30)

    metrics = {f["metric"] for f in out["facts"]}
    assert not metrics & {"profit", "net_profit", "gross_profit"}, (
        "a profit figure was invented from a line with no recorded cost"
    )
    assert out["limitations"], "the gap in the costs was not stated"


async def test_one_shop_never_sees_another_shops_money_through_the_merged_tool(db, tenant_ctx):
    """Both directions, through the merged tool: a shop with money must not leak it to a shop
    without, and the empty shop must not see the rich one's numbers."""
    import uuid

    from app.core.db import bind_tenant
    from app.platform.identity.models import Tenant

    mine = tenant_ctx.tenant_id
    v = await _variant(db, mine, "Mine", cost=10)
    await _delivered_sale(db, mine, [(v, 1, 100)])
    cat = await _category(db, mine)
    await _expense(db, mine, cat, 60)
    other = Tenant(slug=f"t-{uuid.uuid4().hex[:10]}", name="Other")
    db.add(other)
    await db.flush()

    await bind_tenant(db, other.id)
    theirs_profit = (await T._si_finance(db, other.id, report="profit", days=30))["summary"]
    theirs_spend = (await T._si_finance(db, other.id, report="expenses", days=30))["summary"]
    assert _same(theirs_profit["revenue"], "0.00") or float(theirs_profit["revenue"]) == 0
    assert float(theirs_spend["total"]) == 0, "the empty shop saw the other shop's expenses"

    await bind_tenant(db, mine)
    mine_spend = (await T._si_finance(db, mine, report="expenses", days=30))["summary"]
    assert float(mine_spend["total"]) == 60, "this shop lost its own expense"


def test_the_comparison_helper_still_catches_a_real_difference():
    base = {"facts": [{"value": "4", "computed_at": "t1"}]}
    assert _same(base, {"facts": [{"value": "4", "computed_at": "t2"}]})
    assert not _same(base, {"facts": [{"value": "5", "computed_at": "t1"}]})
    assert not _same(base, {"facts": []})
