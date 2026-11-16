"""The data-status read measures how many records each source has, as facts the answer may quote.

Four of the last twenty-four answers were refused by the number gate and rewritten (50 to 73 s
each), and every one quoted a REAL count taken from a tool result: "orders 3, customers 3, stock 5
items, conversations 2" from the status read. The counts sat in ``summary``, which the gate does
not read, so a true figure was refused as if the model had made it up. The gate was never loosened:
the same counts are now registered as measured facts, so a figure the database produced is legal and
a figure from nowhere (77) is still refused. A source the asker may not read is left out entirely,
as the data-recorded summary already does: "no expenses recorded" would itself tell a member of
staff something."""

from __future__ import annotations

import pytest

from app.modules.ai.agents.sales_intelligence import tools as si
from app.modules.ai.agents.sales_intelligence.permissions import asking_with
from app.modules.ai.agents.sales_intelligence.tools import _si_data_status, _si_metric
from tests.test_si_why_tool import _orders

pytestmark = pytest.mark.usefixtures("db")

ALL = {
    "orders:read",
    "customers:read",
    "inventory:read",
    "finance:read",
    "purchasing:read",
}


def _counts(out) -> dict[str, str]:
    return {
        f["filters"]["source"]: f["value"]
        for f in out["facts"]
        if f["metric"] == "records_recorded"
    }


async def _status(db, t, perms):
    with asking_with(perms):
        return await _si_metric(db, t, mode="status")


async def test_a_source_the_asker_may_read_has_its_count_as_a_measured_fact(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    await _orders(db, t, n=3, days_ago=2, total="10.00", tag="cnt")
    out = await _status(db, t, ALL)
    counts = _counts(out)
    assert counts["orders"] == "3"
    fact = next(f for f in out["facts"] if f["filters"].get("source") == "orders")
    assert fact["unit"] == "count"


async def test_an_empty_source_is_a_measured_zero_not_an_absence(db, tenant_ctx):
    out = await _status(db, tenant_ctx.tenant_id, ALL)
    counts = _counts(out)
    assert counts["expenses"] == "0"
    assert counts["orders"] == "0"


async def test_a_source_the_asker_may_not_read_is_left_out_entirely(db, tenant_ctx):
    """A zero would tell staff expenses do not exist; a count above zero, that they do."""
    t = tenant_ctx.tenant_id
    await _orders(db, t, n=2, days_ago=2, total="10.00", tag="perm")
    out = await _status(db, t, {"orders:read"})
    assert set(_counts(out)) == {"orders", "shipments"}
    assert "expenses" not in str(out["facts"])
    assert "purchases" not in str(out["facts"])


async def test_an_unknown_asker_holds_nothing_so_no_count_is_measured(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    await _orders(db, t, n=2, days_ago=2, total="10.00", tag="anon")
    out = await _si_metric(db, t, mode="status")
    assert not out.get("facts")


async def test_the_summary_the_model_already_reads_is_unchanged(db, tenant_ctx):
    t = tenant_ctx.tenant_id
    await _orders(db, t, n=2, days_ago=2, total="10.00", tag="same")
    with asking_with(ALL):
        out = await _si_metric(db, t, mode="status")
    bare = await _si_data_status(db, t)
    assert out["summary"] == bare["summary"]
    assert out["capability"] == "get_data_status"


async def test_no_amount_travels_with_the_counts(db, tenant_ctx):
    """The tool needs no permission, so money must never ride along with a count."""
    t = tenant_ctx.tenant_id
    await _orders(db, t, n=2, days_ago=2, total="98765.00", tag="money")
    out = await _status(db, t, ALL)
    assert "98765" not in str(out["facts"])
    assert {f["unit"] for f in out["facts"]} == {"count"}


async def test_the_registered_status_tool_carries_the_counts_and_the_note(db, tenant_ctx):
    """Through the tool the model reaches, with the wrappers it really has."""
    from app.modules.ai.tools import TOOLS

    t = tenant_ctx.tenant_id
    await _orders(db, t, n=3, days_ago=2, total="10.00", tag="wired")
    TOOLS.pop("si_metric", None)
    si.register_si_tools()
    with asking_with(ALL):
        out = await TOOLS["si_metric"].handler(db, t, mode="status")
    assert _counts(out)["orders"] == "3"
    assert si.MEASURED_FIGURES_NOTE in out["limitations"]
