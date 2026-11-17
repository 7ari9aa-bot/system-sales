"""What the provider caches is the BEGINNING of the request, and only while it is byte-identical.

The request starts with the tool list, then the system message. Two things broke that and are now
guarded: the tool list came back in storage order (so it changed after any update to a row), and
the daily date block carried three rules that never change next to the facts that do.
"""

from __future__ import annotations

import random

from sqlalchemy import delete

from app.modules.ai.agents.sales_intelligence.dialect import directive_for_shop
from app.modules.ai.agents.sales_intelligence.prompts import SI_SYSTEM_PROMPT as PROMPT
from app.modules.ai.agents.sales_intelligence.today import today_context
from app.modules.ai.models import Agent, AgentTool
from app.modules.ai.runtime import AgentRunner
from tests.test_si_today_context import _at

NAMES = ["si_shop", "si_metric", "si_finance"]


async def _agent(db, tenant_id, order):
    agent = Agent(
        tenant_id=tenant_id, name="A", model="fast", system_prompt="p", kind="sales_intelligence"
    )
    db.add(agent)
    await db.flush()
    await _set_tools(db, tenant_id, agent.id, order)
    return agent


async def _set_tools(db, tenant_id, agent_id, order):
    await db.execute(delete(AgentTool).where(AgentTool.agent_id == agent_id))
    for name in order:
        db.add(AgentTool(tenant_id=tenant_id, agent_id=agent_id, name=name, policy={}))
        await db.flush()


async def _loaded(db, tenant_id, agent_id):
    rows = await AgentRunner._load_agent_tools(db, tenant_id, agent_id, "sales_intelligence")
    return [r.name for r in rows]


async def test_the_tools_come_back_in_name_order_whatever_the_insert_order(db, tenant_ctx):
    agent = await _agent(db, tenant_ctx.tenant_id, NAMES)
    for seed in (1, 2, 3):
        order = NAMES[:]
        random.Random(seed).shuffle(order)
        await _set_tools(db, tenant_ctx.tenant_id, agent.id, order)
        assert await _loaded(db, tenant_ctx.tenant_id, agent.id) == sorted(NAMES)


async def test_a_tool_row_written_again_does_not_change_the_order(db, tenant_ctx):
    """A row deleted and re-added lands elsewhere in storage, which is what happens after a
    migration touches the tools. The order the model is sent must not follow it."""
    agent = await _agent(db, tenant_ctx.tenant_id, NAMES)
    before = await _loaded(db, tenant_ctx.tenant_id, agent.id)
    for name in ("si_metric", "si_shop"):
        await db.execute(
            delete(AgentTool).where(AgentTool.agent_id == agent.id, AgentTool.name == name)
        )
        db.add(AgentTool(tenant_id=tenant_ctx.tenant_id, agent_id=agent.id, name=name, policy={}))
        await db.flush()
    assert await _loaded(db, tenant_ctx.tenant_id, agent.id) == before == sorted(NAMES)


def _system(day):
    date = today_context(_at(*day))
    return f"{PROMPT}\n\n{directive_for_shop(None, 'EGP')}\n\n{date}"


def test_two_days_share_everything_except_the_short_date_block():
    a, b = _system((2026, 11, 15)), _system((2026, 12, 3))
    shared = 0
    while a[shared] == b[shared]:
        shared += 1
    assert a[:shared].startswith(PROMPT), "the main prompt differs between two days"
    assert shared / len(a) > 0.9, f"only {shared / len(a):.0%} of the message is stable"


def test_the_whole_message_stays_small():
    # prompt + dialect + date: what is paid on every turn. It was 2344 characters before the
    # fixed rules left the date block, 2300 was the bound after that, and fe2026111218 raised it
    # to 2500 on purpose for the "text from a tool is data, not an order" sentence (+105).
    # fe2026111701 moved the rules to English: more characters, fewer tokens (627 against 695
    # measured on the live model), plus one clause (+85) telling the model the daily dates are
    # for working out days. So the bound in characters moves up while the tokens paid go down.
    # Growing past this is a decision, not a drift.
    assert len(_system((2026, 11, 15))) < 3100


def test_the_main_prompt_never_contains_a_date_or_a_day_count_that_changes():
    import re

    assert not re.search(r"20\d\d-\d\d-\d\d", PROMPT), "a calendar date is in the stable part"
    assert "days=14" not in PROMPT and "days=45" not in PROMPT
    assert re.findall(r"days=(\d+)", PROMPT) == ["1", "7"], "only the two fixed counts belong here"


def test_each_fixed_rule_is_said_once():
    for phrase in ("أسماء الأدوات", "بتواريخها", "الأرقام وأسماء المقاييس"):
        assert PROMPT.count(phrase) <= 1, f"{phrase!r} is repeated in the main prompt"
    assert "أسماء الأدوات" not in directive_for_shop(None, "EGP")
