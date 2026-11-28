"""fe2026111213: every agent that has the three activity tools gets `si_activity` instead.

The self-heal only ADDS missing tools, so without this migration an existing shop's agent would be
offered the three old tools AND `si_activity`: more choices, not fewer. A shop that switched a tool
off must not have it switched back on, and a shop with nothing to move must be left alone.

Runs as the role that really runs migrations (``DATABASE_URL_ADMIN``; the app role is under row
level security, so it could not tell "moved every shop" from "moved one"). Rolled back; skipped when
no admin URL is configured.
"""

from __future__ import annotations

import importlib.util
import json
import uuid
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import get_settings

PATH = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "versions"
    / "fe2026111213_si_activity_tool_merge.py"
)
OLD = ("si_customer_activity", "si_channel_activity", "si_social_comments")


def _load():
    spec = importlib.util.spec_from_file_location("mod_fe2026111213", PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _BindOp:
    def __init__(self, bind: Any) -> None:
        self._bind = bind

    def execute(self, statement: str) -> None:
        self._bind.execute(sa.text(statement))


def test_the_migration_sits_after_the_current_head_and_names_the_three_old_tools() -> None:
    m = _load()
    assert m.revision == "fe2026111213"
    assert m.down_revision == "fe2026111212"
    assert tuple(m._OLD) == OLD


def test_the_old_names_match_what_the_code_no_longer_offers() -> None:
    from app.applications.apparel.modules.ai.agents.sales_intelligence.tools import SI_TOOLS

    assert not set(OLD) & set(SI_TOOLS)
    assert "si_activity" not in SI_TOOLS  # a later merge folded it into si_metric
    assert "si_metric" in SI_TOOLS


@pytest.fixture
async def conn():
    url = get_settings().database_url_admin
    if not url:
        pytest.skip("no DATABASE_URL_ADMIN: the migration role is needed for this test")
    engine = create_async_engine(url, connect_args={"statement_cache_size": 0})
    try:
        async with engine.connect() as c:
            trans = await c.begin()
            yield c
            await trans.rollback()
    finally:
        await engine.dispose()


async def _agent(conn, tools: dict[str, tuple[bool, dict]]) -> tuple[uuid.UUID, uuid.UUID]:
    """A shop with one agent holding ``tools`` = {name: (is_active, policy)}."""
    tid, aid = uuid.uuid4(), uuid.uuid4()
    await conn.execute(
        sa.text("INSERT INTO tenants (id, slug, name) VALUES (:i, :s, 'T')"),
        {"i": tid, "s": f"t-{tid.hex[:12]}"},
    )
    await conn.execute(
        sa.text(
            "INSERT INTO agents (id, tenant_id, kind, name, system_prompt) "
            "VALUES (:i, :t, 'sales_intelligence', 'A', 'p')"
        ),
        {"i": aid, "t": tid},
    )
    for name, (active, policy) in tools.items():
        await conn.execute(
            sa.text(
                "INSERT INTO agent_tools (id, agent_id, name, policy, is_active, tenant_id) "
                "VALUES (gen_random_uuid(), :a, :n, CAST(:p AS jsonb), :act, :t)"
            ),
            {"a": aid, "n": name, "p": json.dumps(policy), "act": active, "t": tid},
        )
    return tid, aid


async def _rows(conn, aid: uuid.UUID) -> dict[str, tuple[bool, dict]]:
    res = await conn.execute(
        sa.text("SELECT name, is_active, policy FROM agent_tools WHERE agent_id = :a"), {"a": aid}
    )
    return {r[0]: (r[1], r[2]) for r in res}


async def _drive(conn, direction: str) -> None:
    module = _load()

    def _run(sync_conn: Any) -> None:
        module.op = _BindOp(sync_conn)
        getattr(module, direction)()

    await conn.run_sync(_run)


ALL_ON = {n: (True, {}) for n in OLD}


async def test_every_agent_with_the_three_old_tools_ends_with_only_si_activity(conn) -> None:
    shops = [await _agent(conn, ALL_ON) for _ in range(3)]  # several shops, not just one

    await _drive(conn, "upgrade")

    for _, aid in shops:
        assert await _rows(conn, aid) == {"si_activity": (True, {})}


async def test_other_tools_of_the_agent_are_not_touched(conn) -> None:
    keep = {"si_top_products": (True, {}), "si_profit_summary": (False, {"x": 1})}
    _, aid = await _agent(conn, {**ALL_ON, **keep})

    await _drive(conn, "upgrade")

    rows = await _rows(conn, aid)
    assert rows["si_top_products"] == (True, {})
    assert rows["si_profit_summary"] == (False, {"x": 1})
    assert set(rows) == {"si_activity", "si_top_products", "si_profit_summary"}


async def test_a_shop_that_switched_every_metric_tool_off_keeps_it_off(conn) -> None:
    _, aid = await _agent(conn, {n: (False, {}) for n in OLD})

    await _drive(conn, "upgrade")

    assert (await _rows(conn, aid))["si_activity"][0] is False


async def test_one_active_old_tool_is_enough_to_keep_the_new_one_on(conn) -> None:
    tools = {n: (False, {}) for n in OLD} | {"si_channel_activity": (True, {})}
    _, aid = await _agent(conn, tools)

    await _drive(conn, "upgrade")

    assert (await _rows(conn, aid))["si_activity"][0] is True


async def test_a_policy_set_on_an_old_tool_is_carried_over(conn) -> None:
    _, aid = await _agent(conn, ALL_ON | {"si_customer_activity": (True, {"max_calls": 3})})

    await _drive(conn, "upgrade")

    assert (await _rows(conn, aid))["si_activity"][1] == {"max_calls": 3}


async def test_an_agent_with_none_of_the_three_is_left_alone(conn) -> None:
    _, aid = await _agent(conn, {"si_top_products": (True, {})})

    await _drive(conn, "upgrade")

    assert set(await _rows(conn, aid)) == {"si_top_products"}


async def test_an_agent_that_already_has_si_activity_is_not_duplicated_or_overwritten(conn) -> None:
    _, aid = await _agent(conn, ALL_ON | {"si_activity": (False, {"keep": True})})

    await _drive(conn, "upgrade")

    assert await _rows(conn, aid) == {"si_activity": (False, {"keep": True})}


async def test_running_it_twice_changes_nothing_more(conn) -> None:
    _, aid = await _agent(conn, ALL_ON)
    await _drive(conn, "upgrade")
    await _drive(conn, "upgrade")
    assert await _rows(conn, aid) == {"si_activity": (True, {})}


async def test_downgrade_puts_the_three_back_and_removes_si_activity(conn) -> None:
    _, aid = await _agent(conn, ALL_ON)
    await _drive(conn, "upgrade")

    await _drive(conn, "downgrade")

    assert await _rows(conn, aid) == ALL_ON


async def test_the_migration_does_not_leak_between_shops(conn) -> None:
    """An agent in one shop must not receive a tool because of another shop's rows."""
    _, off = await _agent(conn, {n: (False, {}) for n in OLD})
    _, on = await _agent(conn, ALL_ON)

    await _drive(conn, "upgrade")

    assert (await _rows(conn, off))["si_activity"][0] is False
    assert (await _rows(conn, on))["si_activity"][0] is True


async def test_it_leaves_the_earlier_merged_tools_alone(conn) -> None:
    """The merges are independent: moving the activity tools must not touch `si_metric`/`si_why`."""
    _, aid = await _agent(
        conn, ALL_ON | {"si_metric": (True, {"keep": 1}), "si_why": (False, {"keep": 2})}
    )

    await _drive(conn, "upgrade")

    rows = await _rows(conn, aid)
    assert rows["si_metric"] == (True, {"keep": 1})
    assert rows["si_why"] == (False, {"keep": 2})
    assert rows["si_activity"] == (True, {})
    assert set(rows) == {"si_metric", "si_why", "si_activity"}
