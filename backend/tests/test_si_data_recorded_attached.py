"""The shop's recorded-data summary rides along with the answer the model reads.

The model called the data-status read in 79% of the questions (23 of 29), each time a model round
of its own (about 5 s and 3.7 thousand tokens) to read 250 tokens. The summary is attached to the
result of si_metric instead, under its own key. These tests pin that it arrives, that it is limited
to what the asker may read, that it opens no door in the number gate, and that a failure to read
it never costs the owner the answer."""

from __future__ import annotations

import uuid

import pytest

from app.applications.apparel.modules.ai.agents.sales_intelligence import tools as si
from app.applications.apparel.modules.ai.agents.sales_intelligence.agent import run_sales_analysis
from app.applications.apparel.modules.ai.agents.sales_intelligence.permissions import asking_with
from app.applications.apparel.modules.ai.agents.sales_intelligence.tools import (
    _recorded_summary,
    _with_data_recorded,
)
from app.applications.apparel.modules.ai.gateway import AIGateway
from app.applications.apparel.modules.ai.providers import ChatCompletionResult, ToolCallRequest
from app.applications.apparel.modules.ai.tools import TOOLS
from app.modules.settings.service import SettingsService
from tests.test_si_agent import _seed

ALL = {
    "orders:read",
    "inventory:read",
    "customers:read",
    "finance:read",
    "purchasing:read",
}


def _status(**recorded):
    names = (
        "orders",
        "shipments",
        "expenses",
        "inventory",
        "purchases",
        "customers",
        "conversations",
    )
    return {
        "capability": "get_data_status",
        "status": "ok",
        "summary": {
            "sources": [
                {
                    "source": n,
                    "recorded": recorded.get(n, False),
                    "count": 7 if recorded.get(n) else 0,
                    "first": "2026-09-17" if recorded.get(n) else None,
                    "last": "2026-09-17" if recorded.get(n) else None,
                }
                for n in names
            ]
        },
    }


def _by_source(rows):
    return {r["source"]: r for r in rows}


# ------------------------------------ what is attached ------------------------------------------


def test_every_source_the_asker_may_read_is_listed_with_dates_and_no_count():
    with asking_with(ALL):
        rows = _recorded_summary(_status(orders=True, expenses=True))
    by = _by_source(rows)
    assert set(by) == {"orders", "shipments", "expenses", "inventory", "purchases", "customers"}
    assert by["orders"] == {
        "source": "orders",
        "recorded": True,
        "first": "2026-09-17",
        "last": "2026-09-17",
    }
    # an empty source says so: that is how "not recorded" is told from "zero"
    assert by["shipments"]["recorded"] is False
    # no row carries a count: a count would be a number the model could quote unmeasured
    assert all("count" not in r for r in rows)


def test_a_source_the_asker_may_not_read_is_left_out_not_shown_empty():
    with asking_with({"orders:read"}):
        rows = _recorded_summary(_status(orders=True, expenses=True, purchases=True))
    names = {r["source"] for r in rows}
    assert "expenses" not in names and "purchases" not in names
    assert {"orders", "shipments"} <= names


def test_an_unknown_asker_gets_nothing():
    """Fails closed, as every other permission check of this agent does."""
    assert _recorded_summary(_status(orders=True, expenses=True)) == []
    with asking_with(None):
        assert _recorded_summary(_status(orders=True)) == []


def test_conversations_are_never_listed():
    """No permission code governs them, so they are not added."""
    with asking_with(ALL):
        rows = _recorded_summary(_status(orders=True))
    assert "conversations" not in {r["source"] for r in rows}


def test_malformed_input_gives_nothing_instead_of_raising():
    with asking_with(ALL):
        for odd in (
            {},
            {"summary": None},
            {"summary": {"sources": "x"}},
            {"summary": {"sources": [1, None]}},
        ):
            assert _recorded_summary(odd) == []


# ------------------------------------ the wrapper itself ----------------------------------------


def _handler(result):
    async def handler(session, tenant_id, **kw):
        return result

    return _with_data_recorded(handler)


@pytest.fixture
def status_is(monkeypatch):
    def _set(value):
        async def fake(session, tenant_id, *, context=None):
            if isinstance(value, Exception):
                raise value
            return value

        monkeypatch.setattr(si, "_si_data_status", fake)

    return _set


async def test_a_result_gets_the_summary_under_its_own_key(status_is):
    status_is(_status(orders=True))
    original = {"status": "ok", "facts": [{"metric": "m"}], "summary": {"x": 1}}
    with asking_with(ALL):
        out = await _handler(original)(None, uuid.uuid4(), mode="value")
    assert out["data_recorded"]
    # everything the tool measured is exactly as it was
    assert {k: v for k, v in out.items() if k != "data_recorded"} == original
    # and the original dict was not modified in place
    assert "data_recorded" not in original


async def test_the_status_read_itself_is_returned_untouched(status_is):
    status_is(_status(orders=True))
    result = _status(orders=True)
    with asking_with(ALL):
        assert await _handler(result)(None, uuid.uuid4(), mode="status") == result
        # also recognised by what it is, not only by how it was called
        assert await _handler(result)(None, uuid.uuid4()) == result


async def test_the_mode_alone_is_enough_to_leave_a_status_read_untouched(status_is):
    """A status result that lost its capability label is still a status read: asked by mode."""
    status_is(_status(orders=True))
    unlabeled = {"status": "ok", "summary": {"sources": []}}
    with asking_with(ALL):
        out = await _handler(unlabeled)(None, uuid.uuid4(), mode="status")
    assert out == unlabeled


async def test_a_failure_to_read_the_status_leaves_the_result_as_it_was(status_is):
    status_is(RuntimeError("db down"))
    original = {"status": "ok", "facts": []}
    with asking_with(ALL):
        assert await _handler(original)(None, uuid.uuid4(), mode="value") == original


async def test_nothing_is_attached_when_the_asker_may_read_nothing(status_is):
    status_is(_status(orders=True))
    original = {"status": "ok", "facts": []}
    assert await _handler(original)(None, uuid.uuid4(), mode="value") == original


async def test_a_non_dict_result_passes_through(status_is):
    status_is(_status(orders=True))
    with asking_with(ALL):
        for odd in (None, [], "text"):
            assert await _handler(odd)(None, uuid.uuid4(), mode="value") == odd


# ------------------------------------ wiring --------------------------------------------------


def test_only_si_metric_carries_it():
    TOOLS.pop("si_metric", None)
    for n in ("si_shop", "si_finance"):
        TOOLS.pop(n, None)
    si.register_si_tools()
    assert getattr(TOOLS["si_metric"].handler, "attaches_data_recorded", False)
    # the other two already answer one named read; their results stay as they were
    for n in ("si_shop", "si_finance"):
        assert not getattr(TOOLS[n].handler, "attaches_data_recorded", False), n


async def test_the_registered_tool_attaches_it_for_every_mode_but_status(db, tenant_ctx):
    TOOLS.pop("si_metric", None)
    si.register_si_tools()
    handler = TOOLS["si_metric"].handler
    with asking_with(ALL):
        status = await handler(db, tenant_ctx.tenant_id, mode="status")
        value = await handler(db, tenant_ctx.tenant_id, mode="value", metric_name="orders_placed")
    assert "data_recorded" not in status
    assert "data_recorded" in value
    assert {r["source"] for r in value["data_recorded"]} >= {"orders", "inventory", "customers"}


def test_the_description_tells_the_model_not_to_ask_for_what_it_already_has():
    """Seen live: the model asked for the status in 79% of the questions. With the summary attached
    that round is wasted unless the description says so."""
    TOOLS.pop("si_metric", None)
    si.register_si_tools()
    text = TOOLS["si_metric"].description
    assert "data_recorded" in text
    assert "only when the owner asks what data you have" in text
    # the old advice ("when an answer comes back empty or surprising") sent it back for it
    assert "empty or surprising" not in text


# ------------------------------- a whole round: the number gate -------------------------------

OWNER_QUESTION = "كام اوردر عندي"
# A model that quotes a COUNT from anywhere but a measured fact must still be refused by the
# strict gate, whatever the attached summary says.
UNMEASURED_COUNT = "عندك 77 أوردر مسجلين."
PLAIN = "الأوردرات مسجلة عندك من أول يوم، بس مفيش رقم مقاس للفترة دي."


async def _round(db, tenant_ctx, monkeypatch, *, first_draft):
    # The analytics agent is gated by analytics_agent.enabled (§settings), default off: a tenant
    # that never switched it on gets "disabled" before the model is reached. These tests are about
    # what the model is handed, so the tenant switches the feature on first.
    await SettingsService(db, tenant_ctx.tenant_id).set(
        "analytics_agent.enabled", True, scope="tenant"
    )
    TOOLS.pop("si_metric", None)
    si.register_si_tools()
    agent = await _seed(db, tenant_ctx.tenant_id)
    calls: list[list[dict]] = []

    async def fake(self, session, tenant_id, *, alias, messages, tools=None, **kwargs):
        calls.append(messages)
        if len(calls) == 1:
            return ChatCompletionResult(
                content=None,
                tool_calls=[
                    ToolCallRequest(
                        id="c1",
                        name="si_metric",
                        arguments={"mode": "explain", "metric_name": "orders_placed"},
                    )
                ],
                tokens_in=1,
                tokens_out=1,
                raw_model="m",
            )
        return ChatCompletionResult(
            content=first_draft if len(calls) == 2 else PLAIN,
            tool_calls=[],
            tokens_in=1,
            tokens_out=1,
            raw_model="m",
        )

    monkeypatch.setattr(AIGateway, "chat", fake)
    result = await run_sales_analysis(
        db,
        tenant_ctx.tenant_id,
        agent_id=agent.id,
        question=OWNER_QUESTION,
        actor_permissions=ALL | {"analytics:read"},
    )
    return result, calls


async def test_the_model_sees_the_summary_in_the_tool_result_without_asking_for_it(
    db, tenant_ctx, monkeypatch
):
    _, calls = await _round(db, tenant_ctx, monkeypatch, first_draft=PLAIN)
    seen = " ".join(str(m.get("content", "")) for m in calls[1])
    assert "data_recorded" in seen
    # it never had to spend a round on the status read
    assert not any("get_data_status" in str(m.get("content", "")) for m in calls[0])


async def test_a_count_quoted_from_nowhere_is_still_refused_by_the_gate(
    db, tenant_ctx, monkeypatch
):
    """The point of the whole design: attaching the summary must not make any figure legal."""
    result, _ = await _round(db, tenant_ctx, monkeypatch, first_draft=UNMEASURED_COUNT)
    assert "77" not in result.answer
