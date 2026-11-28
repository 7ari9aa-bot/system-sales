"""fe2026111220: every agent ends with the three owner tools and nothing a shop turned off turns on.

The self-heal only ADDS missing tools, so without this migration an existing shop's agent would be
offered the eleven old tools AND the new one. ``si_metric`` and ``si_finance`` already exist and are
not touched (a shop's off switch or policy on them stays); only their older companions go.
``si_shop`` is built from the five tools it replaces.

Runs as the role that really runs migrations (``DATABASE_URL_ADMIN``), rolled back; skipped when no
admin URL is configured.
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
    / "fe2026111220_si_three_tools.py"
)
INTO_SHOP = (
    "si_top_products",
    "si_stock_status",
    "si_cashier_summary",
    "si_find_order",
    "si_find_customer",
)
COMPANIONS = ("si_why", "si_activity", "si_data_status", "si_purchasing_summary")
OLD = INTO_SHOP + COMPANIONS
ELEVEN = ("si_metric", "si_finance", *OLD)


def _load():
    spec = importlib.util.spec_from_file_location("mod_fe2026111220", PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _BindOp:
    def __init__(self, bind: Any) -> None:
        self._bind = bind

    def execute(self, statement: str) -> None:
        self._bind.execute(sa.text(statement))


def test_the_migration_sits_after_the_current_head_and_names_every_old_tool() -> None:
    m = _load()
    assert m.revision == "fe2026111220"
    assert m.down_revision == "fe2026111219"
    assert set(m._OLD) == set(OLD)


def test_the_old_names_match_what_the_code_no_longer_offers() -> None:
    from app.modules.ai.agents.sales_intelligence.tools import SI_TOOLS

    assert not set(OLD) & set(SI_TOOLS)
    # si_cashier arrived after this migration, so the three are a subset of today's set
    assert {"si_metric", "si_shop", "si_finance"} <= set(SI_TOOLS)
    assert "si_cashier" in SI_TOOLS
    # the eleven the owner had are exactly what the three replace
    assert set(ELEVEN) == set(OLD) | {"si_metric", "si_finance"}


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


ALL_ON = {n: (True, {}) for n in ELEVEN}
THREE = {"si_metric", "si_shop", "si_finance"}


async def test_every_agent_with_the_eleven_ends_with_exactly_the_three(conn) -> None:
    shops = [await _agent(conn, ALL_ON) for _ in range(3)]  # several shops, not just one

    await _drive(conn, "upgrade")

    for _, aid in shops:
        rows = await _rows(conn, aid)
        assert set(rows) == THREE
        assert all(active for active, _ in rows.values())


async def test_the_existing_metric_and_finance_rows_are_never_touched(conn) -> None:
    """A shop's choice on them (off, a policy) survives, even when a companion was on."""
    tools = ALL_ON | {"si_metric": (False, {"keep": 1}), "si_finance": (False, {"keep": 2})}
    _, aid = await _agent(conn, tools)

    await _drive(conn, "upgrade")

    rows = await _rows(conn, aid)
    assert rows["si_metric"] == (False, {"keep": 1}), "a switched-off metric tool was turned on"
    assert rows["si_finance"] == (False, {"keep": 2}), "switched-off money was turned on"


async def test_money_stays_off_when_only_purchases_were_on(conn) -> None:
    """The case that matters: expenses and profit off, purchases on. Folding must not open them."""
    tools = {"si_finance": (False, {}), "si_purchasing_summary": (True, {})}
    _, aid = await _agent(conn, tools)

    await _drive(conn, "upgrade")

    assert await _rows(conn, aid) == {"si_finance": (False, {})}


async def test_a_shop_that_switched_every_shop_read_off_keeps_it_off(conn) -> None:
    _, aid = await _agent(conn, {n: (False, {}) for n in INTO_SHOP})

    await _drive(conn, "upgrade")

    assert (await _rows(conn, aid)) == {"si_shop": (False, {})}


async def test_one_active_shop_read_is_enough_to_turn_si_shop_on(conn) -> None:
    tools = {n: (False, {}) for n in INTO_SHOP} | {"si_find_customer": (True, {})}
    _, aid = await _agent(conn, tools)

    await _drive(conn, "upgrade")

    assert (await _rows(conn, aid))["si_shop"][0] is True


async def test_a_policy_set_on_an_old_shop_read_is_carried_over(conn) -> None:
    _, aid = await _agent(conn, ALL_ON | {"si_stock_status": (True, {"max_calls": 3})})

    await _drive(conn, "upgrade")

    assert (await _rows(conn, aid))["si_shop"][1] == {"max_calls": 3}


async def test_an_agent_with_none_of_the_five_gets_no_shop_tool_here(conn) -> None:
    """The self-heal attaches it on the next question; the migration invents nothing."""
    _, aid = await _agent(conn, {"si_metric": (True, {}), "si_why": (True, {})})

    await _drive(conn, "upgrade")

    assert await _rows(conn, aid) == {"si_metric": (True, {})}


async def test_an_agent_that_already_has_si_shop_is_not_duplicated_or_overwritten(conn) -> None:
    _, aid = await _agent(conn, ALL_ON | {"si_shop": (False, {"keep": True})})

    await _drive(conn, "upgrade")

    assert (await _rows(conn, aid))["si_shop"] == (False, {"keep": True})


async def test_running_it_twice_changes_nothing_more(conn) -> None:
    _, aid = await _agent(conn, ALL_ON)
    await _drive(conn, "upgrade")
    once = await _rows(conn, aid)
    await _drive(conn, "upgrade")
    assert await _rows(conn, aid) == once


async def test_other_tools_of_the_agent_are_not_touched(conn) -> None:
    _, aid = await _agent(conn, ALL_ON | {"search_catalog": (True, {"x": 1})})

    await _drive(conn, "upgrade")

    rows = await _rows(conn, aid)
    assert rows["search_catalog"] == (True, {"x": 1})
    assert set(rows) == THREE | {"search_catalog"}


async def test_the_migration_does_not_leak_between_shops(conn) -> None:
    """An agent in one shop must not receive a tool state because of another shop's rows."""
    _, off = await _agent(conn, {n: (False, {}) for n in INTO_SHOP})
    _, on = await _agent(conn, {n: (True, {}) for n in INTO_SHOP})

    await _drive(conn, "upgrade")

    assert (await _rows(conn, off))["si_shop"][0] is False
    assert (await _rows(conn, on))["si_shop"][0] is True


async def test_downgrade_puts_the_old_ones_back_and_removes_si_shop(conn) -> None:
    _, aid = await _agent(conn, ALL_ON)
    await _drive(conn, "upgrade")

    await _drive(conn, "downgrade")

    assert await _rows(conn, aid) == ALL_ON
