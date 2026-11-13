"""fe2026111206: the Sales Intelligence prompt reaches shops that already have the agent.

An agent row's ``system_prompt`` ranks above the definition in code, so editing the constant alone
changes nothing for a shop that already exists. The migration rewrites the stored text, and only
where it still holds the previous canonical text. What it must never do: overwrite a prompt the shop
owner edited, or touch another agent kind.

Runs as the role that really runs migrations (``DATABASE_URL_ADMIN``). The app role is under row
level security, so a test on it could not tell "updated every shop" from "updated one".
Everything is rolled back; skipped when no admin URL is configured.
"""

from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import get_settings
from app.modules.ai.agents.sales_intelligence.prompts import SI_SYSTEM_PROMPT

PATH = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "versions"
    / "fe2026111206_si_prompt_sales_means_money.py"
)


def _load():
    spec = importlib.util.spec_from_file_location("si_prompt_migration_under_test", PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _BindOp:
    def __init__(self, bind: Any) -> None:
        self._bind = bind

    def get_bind(self) -> Any:
        return self._bind

    def execute(self, statement: str) -> None:
        self._bind.execute(sa.text(statement))


def test_the_migration_sits_on_the_current_head_and_ships_the_code_prompt() -> None:
    module = _load()
    assert module.revision == "fe2026111206"
    assert module.down_revision == "fe2026111205"
    # fe2026111206 is already in production, so its text is frozen as shipped: the code prompt has
    # moved on since (fe2026111208), and that later migration is what carries shops to it
    assert module._OLD != module._NEW
    assert "ابدأ بالإيراد المحصّل" in module._NEW


def test_the_code_prompt_says_sales_means_money_and_names_real_metrics() -> None:
    from app.modules.analytics import compiler

    computable = compiler.computable_metric_names()
    for name in ("collected_revenue", "delivered_revenue", "orders_placed"):
        assert name in SI_SYSTEM_PROMPT
        assert name in computable, f"the prompt sends the model to {name}, which no tool computes"
    assert "مش عدد الأوردرات" in SI_SYSTEM_PROMPT


@pytest.fixture
async def admin_conn():
    url = get_settings().database_url_admin
    if not url:
        pytest.skip("no DATABASE_URL_ADMIN: the migration role is needed for this test")
    engine = create_async_engine(url, connect_args={"statement_cache_size": 0})
    try:
        async with engine.connect() as conn:
            trans = await conn.begin()
            yield conn
            await trans.rollback()
    finally:
        await engine.dispose()


async def _shop(conn, kind: str, prompt: str | None) -> uuid.UUID:
    tid = uuid.uuid4()
    await conn.execute(
        sa.text("INSERT INTO tenants (id, slug, name) VALUES (:i, :s, 'T')"),
        {"i": tid, "s": f"t-{tid.hex[:12]}"},
    )
    aid = uuid.uuid4()
    await conn.execute(
        sa.text(
            "INSERT INTO agents (id, tenant_id, kind, name, system_prompt) "
            "VALUES (:i, :t, :k, 'A', :p)"
        ),
        {"i": aid, "t": tid, "k": kind, "p": prompt},
    )
    return aid


async def _prompt(conn, agent_id: uuid.UUID) -> str | None:
    return (
        await conn.execute(
            sa.text("SELECT system_prompt FROM agents WHERE id = :i"), {"i": agent_id}
        )
    ).scalar_one()


async def _drive(conn, direction: str) -> None:
    module = _load()

    def _run(sync_conn: Any) -> None:
        module.op = _BindOp(sync_conn)
        getattr(module, direction)()

    await conn.run_sync(_run)


async def test_every_shop_on_the_old_text_is_moved_and_nobody_else_is_touched(admin_conn) -> None:
    m = _load()
    old_a = await _shop(admin_conn, "sales_intelligence", m._OLD)
    old_b = await _shop(admin_conn, "sales_intelligence", m._OLD)  # a second shop, not just one
    edited = await _shop(admin_conn, "sales_intelligence", "برومبت عدّله صاحب المحل بنفسه")
    empty = await _shop(admin_conn, "sales_intelligence", None)
    # the same old text on ANOTHER kind of agent is none of this migration's business
    other_kind = await _shop(admin_conn, "customer", m._OLD)

    await _drive(admin_conn, "upgrade")

    assert await _prompt(admin_conn, old_a) == m._NEW
    assert await _prompt(admin_conn, old_b) == m._NEW
    assert await _prompt(admin_conn, edited) == "برومبت عدّله صاحب المحل بنفسه"
    assert await _prompt(admin_conn, empty) is None
    assert await _prompt(admin_conn, other_kind) == m._OLD


async def test_running_it_twice_changes_nothing_more(admin_conn) -> None:
    m = _load()
    a = await _shop(admin_conn, "sales_intelligence", m._OLD)
    await _drive(admin_conn, "upgrade")
    await _drive(admin_conn, "upgrade")
    assert await _prompt(admin_conn, a) == m._NEW


async def test_downgrade_restores_only_what_it_wrote(admin_conn) -> None:
    m = _load()
    moved = await _shop(admin_conn, "sales_intelligence", m._OLD)
    edited = await _shop(admin_conn, "sales_intelligence", "نص تاني")
    await _drive(admin_conn, "upgrade")
    await _drive(admin_conn, "downgrade")
    assert await _prompt(admin_conn, moved) == m._OLD
    assert await _prompt(admin_conn, edited) == "نص تاني"


async def test_updated_at_moves_for_the_rows_it_changes_and_not_for_the_rest(admin_conn) -> None:
    m = _load()
    moved = await _shop(admin_conn, "sales_intelligence", m._OLD)
    kept = await _shop(admin_conn, "sales_intelligence", "نص تاني")
    await admin_conn.execute(
        sa.text("UPDATE agents SET updated_at = '2020-01-01' WHERE id IN (:a, :b)"),
        {"a": moved, "b": kept},
    )
    await _drive(admin_conn, "upgrade")
    rows = {
        r.id: r.updated_at.year
        for r in (
            await admin_conn.execute(
                sa.text("SELECT id, updated_at FROM agents WHERE id IN (:a, :b)"),
                {"a": moved, "b": kept},
            )
        )
    }
    assert rows[moved] > 2020
    assert rows[kept] == 2020
