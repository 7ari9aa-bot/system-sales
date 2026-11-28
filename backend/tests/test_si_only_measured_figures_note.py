"""A tool that measured something tells the model to quote only what it measured.

Fourteen answers were refused by the number gate in 2.5 hours, and ten of them (71%) over a small
whole number the MODEL added: the days in October ("31"), a sum it worked out itself ("1112.98"),
the days since the last order ("58"), "these are all your customers (3)" from a page size. Each
refusal cost a rewrite of 30 to 35 s. The gate was right every time. The cheaper fix is that the
number is never written, so the first draft passes. The note rides with the data, the way the
"nothing was measured" note already does."""

from __future__ import annotations

import uuid

from app.applications.apparel.modules.ai.agents.sales_intelligence.tools import (
    MEASURED_FIGURES_NOTE,
    NO_FIGURES_NOTE,
    _only_measured_figures,
    _say_it_without_figures,
)


def _wrapped(result):
    async def handler(session, tenant_id, **kw):
        return result

    return _only_measured_figures(handler)


async def _call(result):
    return await _wrapped(result)(None, uuid.uuid4())


async def test_a_result_with_facts_gets_the_note_and_keeps_its_own_limits():
    out = await _call({"status": "ok", "facts": [{"metric": "m"}], "limitations": ["x"]})
    assert out["limitations"] == ["x", MEASURED_FIGURES_NOTE]
    assert out["facts"] == [{"metric": "m"}]


async def test_a_result_with_no_limitations_key_still_gets_it():
    out = await _call({"status": "ok", "facts": [{"metric": "m"}]})
    assert out["limitations"] == [MEASURED_FIGURES_NOTE]


async def test_it_is_never_added_twice():
    out = await _call(
        {"status": "ok", "facts": [{"metric": "m"}], "limitations": [MEASURED_FIGURES_NOTE]}
    )
    assert out["limitations"].count(MEASURED_FIGURES_NOTE) == 1


async def test_a_result_that_measured_nothing_is_left_to_the_other_note():
    """Nothing measured has its own, stronger instruction: no figure at all."""
    result = {"status": "no_data", "facts": [], "limitations": ["x"]}
    assert await _call(result) == result


async def test_a_refusal_or_error_shape_is_untouched():
    for result in ({"error": "nope"}, {"status": "refused"}, None, "text"):
        assert await _call(result) == result


async def test_the_two_notes_never_both_ride_on_one_result():
    async def handler(session, tenant_id, **kw):
        return {"status": "no_data", "facts": []}

    both = _only_measured_figures(_say_it_without_figures(handler))
    out = await both(None, uuid.uuid4())
    assert out["limitations"] == [NO_FIGURES_NOTE]


def test_the_note_names_the_numbers_the_model_actually_invented():
    """Each phrase answers one of the refusals seen live; losing one reopens that refusal."""
    text = MEASURED_FIGURES_NOTE.lower()
    for needle in ("facts", "sum", "difference", "days", "month", "all"):
        assert needle in text, needle


async def test_every_registered_tool_is_wrapped():
    """The wiring: a wrapper that is never applied would pass every test above."""
    from app.applications.apparel.modules.ai.agents.sales_intelligence import tools as si
    from app.applications.apparel.modules.ai.tools import TOOLS

    TOOLS.pop("si_shop", None)
    si.register_si_tools()
    names = [n for n in TOOLS if n.startswith("si_")]
    assert names
    for n in names:
        assert getattr(TOOLS[n].handler, "only_measured_figures", False), n


async def test_the_real_top_customers_tool_carries_it_with_its_measured_total(db, tenant_ctx):
    """Through the registered tool, as the model reaches it, with real rows behind it."""
    from datetime import UTC, datetime, timedelta
    from decimal import Decimal

    from app.applications.apparel.modules.ai.agents.sales_intelligence import tools as si
    from app.applications.apparel.modules.ai.agents.sales_intelligence.permissions import asking_with
    from app.applications.apparel.modules.ai.tools import TOOLS
    from app.applications.apparel.modules.customers.models import Customer
    from app.applications.apparel.modules.orders.models import Order

    t = tenant_ctx.tenant_id
    c = Customer(tenant_id=t, name="Real", phone="+201000000042")
    db.add(c)
    await db.flush()
    db.add(
        Order(
            tenant_id=t,
            number="O-REAL-1",
            customer_id=c.id,
            status="confirmed",
            grand_total=Decimal("50"),
            placed_at=datetime.now(UTC) - timedelta(days=3),
        )
    )
    await db.flush()
    TOOLS.pop("si_shop", None)
    si.register_si_tools()
    with asking_with({"customers:read", "orders:read"}):
        out = await TOOLS["si_shop"].handler(db, t, view="top_customers", days=30, limit=5)
    assert MEASURED_FIGURES_NOTE in out["limitations"]
    measured = {f["metric"]: f["value"] for f in out["facts"]}
    assert measured["customers_who_ordered"] == "1"
    assert measured["days_since_last_order"] == "3"
