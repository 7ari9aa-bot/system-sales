"""The owner assistant is told what day it is, in the shop's own time zone.

Production proof (a real run's messages): the system text held no year and no "today". An owner who
asks "this month" or "yesterday" left the model to guess how many days back that is, and the tools
only take a trailing ``days`` count. The windows the tools read END YESTERDAY (today is not complete
yet), so "this month" on the 15th is 14 days, not 15, and on the 1st there is no completed day of
this month at all. The code works those numbers out, because a model should not do date arithmetic.

This is FACTS for the model (a date and day counts), never wording for the owner: no reply text is
prepared here.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.applications.apparel.modules.ai.agents.sales_intelligence.today import today_context

CAIRO = ZoneInfo("Africa/Cairo")


def _at(y, m, d, hh=12, mm=0, tz=CAIRO):
    return datetime(y, m, d, hh, mm, tzinfo=tz)


def test_it_states_the_shop_s_calendar_day_not_utc():
    # 02:26 in Cairo on the 15th is still the 14th in UTC: the owner's day is the 15th
    text = today_context(_at(2026, 11, 15, 2, 26))
    assert "2026-11-15" in text
    assert "2026-11-14" in text  # yesterday is named too
    assert "الأحد" in text or "Sunday" in text


def test_it_converts_a_utc_clock_into_the_shop_day():
    from datetime import UTC

    text = today_context(datetime(2026, 11, 14, 22, 30, tzinfo=UTC), CAIRO)
    assert "2026-11-15" in text.split("\n")[0], "the shop is already on the 15th"


@pytest.mark.parametrize(
    ("today", "this_month_days"),
    [((2026, 11, 15), 14), ((2026, 11, 2), 1), ((2026, 12, 31), 30), ((2027, 3, 10), 9)],
)
def test_this_month_is_the_completed_days_since_the_first(today, this_month_days):
    """Counted independently of the code: the completed days of the month are 1..(today - 1)."""
    assert this_month_days == today[2] - 1, "the expected number in this test is itself wrong"
    line = next(row for row in today_context(_at(*today)).split("\n") if "هذا الشهر" in row)
    assert f"days={this_month_days})" in line or f"days={this_month_days}." in line
    other = [n for n in range(1, 40) if n != this_month_days]
    assert not any(f"days={n}." in line or f"days={n})" in line for n in other)


def test_on_the_first_there_is_no_completed_day_of_this_month():
    """The window ends yesterday, so on the 1st nothing of this month is readable yet."""
    text = today_context(_at(2026, 11, 1))
    line = next(row for row in text.split("\n") if "هذا الشهر" in row)
    assert "days=" not in line, "told the model a days count that would return last month"
    assert "لسه" in line or "no completed" in line.lower()


def test_yesterday_is_one_day_and_last_seven_is_seven():
    """These two counts never change, so they live in the main prompt (the stable part of the
    message) and not in the daily date block. Each is read from ITS OWN clause."""
    from app.applications.apparel.modules.ai.agents.sales_intelligence.prompts import SI_SYSTEM_PROMPT as P

    assert "Yesterday is days=1" in P and "days=2" not in P.split("Yesterday is days=1")[1][:12]
    assert "last week is days=7" in P and "days=8" not in P
    block = today_context(_at(2026, 11, 15))
    assert "days=1." not in block and "days=7." not in block, (
        "a fixed rule is back in the daily block"
    )


def test_last_month_is_given_as_its_dates_and_how_far_back_it_reaches():
    """A trailing count cannot express a past calendar month on its own, so the model is given the
    month's dates and told how many days back its start is, to choose a window that covers it."""
    text = today_context(_at(2026, 11, 15))
    line = next(row for row in text.split("\n") if "الشهر اللي فات" in row)
    assert "2026-10-01" in line and "2026-10-31" in line
    assert "days=45" in line  # 15 Nov back to 1 Oct is 45 days


def test_last_month_across_a_year_boundary():
    text = today_context(_at(2027, 1, 10))
    line = next(row for row in text.split("\n") if "الشهر اللي فات" in row)
    assert "2026-12-01" in line and "2026-12-31" in line
    assert "days=40" in line  # 10 Jan back to 1 Dec


def test_the_longest_window_the_tools_accept_is_stated_so_it_is_never_exceeded():
    from app.applications.apparel.modules.ai.agents.sales_intelligence.prompts import SI_SYSTEM_PROMPT as P
    from app.applications.apparel.modules.ai.agents.sales_intelligence.today import MONEY_MAX_DAYS, SALES_MAX_DAYS

    assert f"{SALES_MAX_DAYS} days" in P and str(MONEY_MAX_DAYS) in P
    assert (
        "90" not in today_context(_at(2026, 11, 15)).replace("2026", "").replace("-", " ").split()
    )


def test_the_daily_block_holds_only_what_changes_so_the_cache_prefix_survives():
    """The date block rides last. Everything fixed is in the main prompt, so two different days
    share the whole prompt and the dialect and differ only inside this short block."""
    from app.applications.apparel.modules.ai.agents.sales_intelligence.prompts import SI_SYSTEM_PROMPT as P

    a = today_context(_at(2026, 11, 15))
    b = today_context(_at(2026, 12, 3))
    assert a != b
    assert len(a) < 260, "the daily block grew: a fixed rule probably moved back into it"
    system_a, system_b = f"{P}\n\n{a}", f"{P}\n\n{b}"
    shared = 0
    while system_a[shared] == system_b[shared]:
        shared += 1
    assert shared >= len(P), "the main prompt itself differs between two days"


def test_it_is_deterministic_for_the_same_instant():
    assert today_context(_at(2026, 11, 15)) == today_context(_at(2026, 11, 15))


def test_it_never_contains_text_meant_to_be_said_to_the_owner():
    """Facts only: it must not read as a canned reply (the rule is no fixed replies)."""
    text = today_context(_at(2026, 11, 15))
    for banned in ("أهلا", "أهلاً", "تمام", "حاضر", "مرحبا", "شكراً", "شكرا"):
        assert banned not in text


# ----------------------------- on the real path to the model ---------------------------------


async def _messages_sent(db, tenant_ctx, monkeypatch, *, question="مبيعات الشهر ده؟", kind=None):
    from app.applications.apparel.modules.ai.agents.sales_intelligence.agent import run_sales_analysis
    from app.applications.apparel.modules.ai.gateway import AIGateway
    from app.applications.apparel.modules.ai.providers import ChatCompletionResult
    from tests.test_si_tools_reach_the_chat_agent import _agent

    seen = {}

    async def fake_chat(self, session, tenant_id, *, alias, messages, tools=None, **kwargs):
        seen["messages"] = messages
        return ChatCompletionResult(
            content="تمام", tool_calls=[], tokens_in=1, tokens_out=1, raw_model="m"
        )

    monkeypatch.setattr(AIGateway, "chat", fake_chat)
    # The analytics agent is gated by analytics_agent.enabled (§settings): a tenant that has
    # not turned it on never reaches the model, so the run returns "disabled" before any chat
    # call. This lane is about what the model is TOLD, so it turns the agent on first.
    from app.modules.settings.service import SettingsService

    await SettingsService(db, tenant_ctx.tenant_id).set(
        "analytics_agent.enabled", True, scope="tenant"
    )
    agent = await _agent(db, tenant_ctx.tenant_id, kind or "sales_intelligence", ("si_metric",))
    agent.system_prompt = None
    await db.flush()
    await run_sales_analysis(db, tenant_ctx.tenant_id, agent_id=agent.id, question=question)
    return seen["messages"]


def _system(messages) -> str:
    return "\n".join(m["content"] for m in messages if m["role"] == "system")


async def test_the_model_is_told_today_on_the_real_path(db, tenant_ctx, monkeypatch):
    from app.applications.apparel.modules.ai.agents.sales_intelligence import agent as A

    monkeypatch.setattr(A, "_shop_now", lambda zone: _at(2026, 11, 15, 2, 26, zone))
    system = _system(await _messages_sent(db, tenant_ctx, monkeypatch))

    assert "2026-11-15" in system
    assert "days=14" in system, "the model was not given what 'this month' means in days"


async def test_the_date_comes_after_the_rules_and_alongside_the_dialect(
    db, tenant_ctx, monkeypatch
):
    from app.applications.apparel.modules.ai.agents.sales_intelligence import agent as A

    monkeypatch.setattr(A, "_shop_now", lambda zone: _at(2026, 11, 15, 12, 0, zone))
    system = _system(await _messages_sent(db, tenant_ctx, monkeypatch))

    rules_end = system.index("read only")
    assert system.index("2026-11-15") > rules_end, "the date came before the rules"
    assert "لهجة" in system or "مصري" in system or "المصرية" in system, "the dialect was lost"


async def test_a_failure_in_the_date_never_costs_the_owner_an_answer(db, tenant_ctx, monkeypatch):
    from app.applications.apparel.modules.ai.agents.sales_intelligence import agent as A

    def boom(zone):
        raise RuntimeError("clock unavailable")

    monkeypatch.setattr(A, "_shop_now", boom)
    messages = await _messages_sent(db, tenant_ctx, monkeypatch)

    system = _system(messages)
    assert messages, "the run did not reach the model"
    assert "read only" in system, "the rules vanished with the date"
    assert "لهجة" in system or "المصرية" in system, "the dialect vanished with the date"
    assert "النهارده عند صاحب المحل" not in system, "a date block appeared although it failed"


async def test_a_failure_in_the_dialect_never_costs_the_date(db, tenant_ctx, monkeypatch):
    from app.applications.apparel.modules.ai.agents.sales_intelligence import agent as A
    from app.applications.apparel.modules.ai.agents.sales_intelligence import dialect

    def boom(*args, **kwargs):
        raise RuntimeError("dialect unavailable")

    monkeypatch.setattr(dialect, "directive_for_shop", boom)
    monkeypatch.setattr(A, "_shop_now", lambda zone: _at(2026, 11, 15, 12, 0, zone))
    system = _system(await _messages_sent(db, tenant_ctx, monkeypatch))

    assert "2026-11-15" in system, "the date vanished with the dialect"
    assert "read only" in system


async def test_the_customer_agent_is_never_given_the_owner_date_block(db, tenant_ctx, monkeypatch):
    """Another agent kind goes through the same runner but must be composed exactly as before."""
    from app.applications.apparel.modules.ai.agents.sales_intelligence import agent as A

    monkeypatch.setattr(A, "_shop_now", lambda zone: _at(2026, 11, 15, 12, 0, zone))
    from app.applications.apparel.modules.ai.models import Agent
    from app.applications.apparel.modules.ai.runtime import AgentRunner

    cust = Agent(
        tenant_id=tenant_ctx.tenant_id, name="C", model="fast", system_prompt="رد", kind="customer"
    )
    composed = AgentRunner._compose_system_content(cust)
    assert "2026-11-15" not in composed
    assert composed == "رد"


import calendar  # noqa: E402


@pytest.mark.parametrize("month", range(1, 13))
def test_last_month_dates_are_right_for_every_month_of_the_year(month):
    """28, 29, 30 and 31 day months, and the January -> December year change, one by one."""
    today = (2027, month, 20)
    text = today_context(_at(*today))
    line = next(r for r in text.split("\n") if "الشهر اللي فات" in r)

    prev_year, prev_month = (2027, month - 1) if month > 1 else (2026, 12)
    last_day = calendar.monthrange(prev_year, prev_month)[1]
    first = f"{prev_year}-{prev_month:02d}-01"
    last = f"{prev_year}-{prev_month:02d}-{last_day:02d}"
    assert first in line and last in line, f"expected {first}..{last} in: {line}"

    from datetime import date

    back = (date(*today) - date(prev_year, prev_month, 1)).days
    assert (
        f"days={back} " in line
        or f"days={back}(" in line
        or f"days={back}\u200f" in line
        or (f"days={back}" in line)
    )
    for wrong in (back - 1, back + 1):
        assert f"days={wrong} " not in line and f"days={wrong}(" not in line


def test_leap_february_has_29_days():
    line = next(r for r in today_context(_at(2028, 3, 5)).split("\n") if "الشهر اللي فات" in r)
    assert "2028-02-01" in line and "2028-02-29" in line


@pytest.mark.parametrize(
    ("day", "name"),
    [
        (9, "الإثنين"),
        (10, "الثلاثاء"),
        (11, "الأربعاء"),
        (12, "الخميس"),
        (13, "الجمعة"),
        (14, "السبت"),
        (15, "الأحد"),
    ],
)
def test_every_weekday_has_its_own_name(day, name):
    """2026-11-09 is a Monday: all seven names, so a swapped pair cannot hide."""
    first = today_context(_at(2026, 11, day)).split("\n")[0]
    assert name in first, f"{day} Nov 2026 should be {name}: {first}"


async def test_the_dialect_comes_before_the_date_in_the_real_message(db, tenant_ctx, monkeypatch):
    """Measured on the text the model receives, not by reading the source."""
    from app.applications.apparel.modules.ai.agents.sales_intelligence import agent as A

    monkeypatch.setattr(A, "_shop_now", lambda zone: _at(2026, 11, 15, 12, 0, zone))
    system = _system(await _messages_sent(db, tenant_ctx, monkeypatch))

    date_at = system.index("النهارده عند صاحب المحل")
    dialect_at = max(system.find("لهجة"), system.find("المصرية"))
    assert 0 <= dialect_at < date_at, "the date block came before the dialect"


# ----------------------- the corrective second draft must say it the same way -----------------


class _FakeSession:
    def __init__(self, agent):
        self._agent = agent

    async def get(self, model, obj_id):
        return self._agent


def _regen_agent():
    import uuid
    from types import SimpleNamespace

    return SimpleNamespace(
        id=uuid.uuid4(),
        kind="sales_intelligence",
        model="fast",
        system_prompt="analyze",
        persona_prompt=None,
        temperature=0.2,
        max_output_tokens=200,
    )


async def _regen_system_text(monkeypatch, **extra) -> str:
    """The system message the corrective regeneration sends to the model."""
    import uuid

    from app.applications.apparel.modules.ai.agents.sales_intelligence.coverage import regenerate_on_coverage_gap
    from app.applications.apparel.modules.ai.gateway import AIGateway
    from app.applications.apparel.modules.ai.providers import ChatCompletionResult

    agent = _regen_agent()
    seen = {}

    async def fake_chat(self, session, tenant_id, *, alias, messages, tools=None, **kwargs):
        seen["messages"] = messages
        return ChatCompletionResult(
            content="المبيعات قيمة الطلبات الموضوعة: 5",
            tool_calls=[],
            tokens_in=1,
            tokens_out=1,
            raw_model="m",
        )

    monkeypatch.setattr(AIGateway, "chat", fake_chat)
    await regenerate_on_coverage_gap(
        _FakeSession(agent),
        uuid.uuid4(),
        agent_id=agent.id,
        run_id=None,
        question="كام مبيعات وكام طلبات؟",
        history=None,
        draft="عدد الطلبات: 5",
        evidence={"facts": [{"metric": "orders_placed", "value": 5}]},
        allowed_numbers={"5"},
        findings=[],
        tool_calls_made=[],
        **extra,
    )
    return "\n".join(m["content"] for m in seen["messages"] if m["role"] == "system")


async def test_the_second_draft_carries_the_same_dialect_and_date_as_the_first(monkeypatch):
    """The first answer is written with the shop's dialect and today's date. When it is thin and a
    corrective second draft is requested, that draft used to be built from the bare rules, so it
    came back in a different voice and without knowing the day, on answers already going wrong."""
    directive = "اكتب بالعامية المصرية.\n\nالنهارده عند صاحب المحل: 2026-11-15 (الأحد)."
    system = await _regen_system_text(monkeypatch, style_directive=directive)

    assert system.startswith("analyze"), "the rules must still come first"
    assert system.endswith(directive), "the dialect and date must ride last, as on the first draft"


async def test_without_a_directive_the_second_draft_is_exactly_what_it_was(monkeypatch):
    system = await _regen_system_text(monkeypatch)
    assert system == "analyze"


async def test_the_real_caller_hands_the_second_draft_the_directive_it_built(
    db, tenant_ctx, monkeypatch
):
    """Wired end to end: the regeneration gets the directive built for the first draft."""
    from app.applications.apparel.modules.ai.agents.sales_intelligence import agent as A
    from app.applications.apparel.modules.ai.agents.sales_intelligence import coverage as C

    got = {}

    async def spy(*args, **kwargs):
        got["directive"] = kwargs.get("style_directive")
        return None, None, None

    monkeypatch.setattr(A, "regenerate_on_coverage_gap", spy)
    monkeypatch.setattr(A, "_shop_now", lambda zone: _at(2026, 11, 15, 12, 0, zone))
    assert C.regenerate_on_coverage_gap is not None
    messages = await _messages_sent(db, tenant_ctx, monkeypatch, question="كام مبيعات وكام طلبات؟")

    assert messages
    assert got.get("directive"), "the regeneration was called without the directive"
    assert "2026-11-15" in got["directive"]
