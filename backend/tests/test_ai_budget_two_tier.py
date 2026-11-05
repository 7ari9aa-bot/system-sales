"""Two-tier AI budget (fe2026110504) — soft warns, hard stop holds.

The merchant contract the owner console now sets:

* SOFT tier — crossing ``soft_cap`` sends the owners a renewal-asking
  notification (distinct kind, once per month) and usage CONTINUES;
* HARD tier — crossing the cap under ``on_exceed=block`` stamps the durable
  ``hard_stopped_at`` on the tenant-scope policy; from then on EVERY
  reservation is refused even if spend reads zero — a state, not a
  recomputation;
* the lift — ``lift_hard_stop`` (auto on tenant reactivation, manual from the
  console) clears the stop and honours it for the rest of the period: within
  the same "YYYY-MM" a lifted stop is never re-stamped, so a mid-month
  renewal cannot flip-flop stop/lift/stop.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import app.core.model_registry  # noqa: F401  (loads every model so foreign keys resolve alone)
import app.modules.ai.budget as budget_module
from app.core.tenancy import dispatch_tenant_reactivated_hooks, tenant_reactivated_hooks
from app.modules.ai.budget import AIBudgetExhaustedError, lift_hard_stop, reserve_budget
from app.modules.ai.models import BudgetPolicy
from app.modules.notifications.models import Notification


def _spend(value: Decimal):
    async def _inner(_session, _tenant_id, *, agent_id=None):
        return value

    return _inner


async def _policy(db: AsyncSession, tenant_id, **overrides) -> BudgetPolicy:
    row = BudgetPolicy(
        tenant_id=tenant_id,
        period="monthly",
        hard_cap=Decimal(str(overrides.pop("hard_cap", "10"))),
        on_exceed=overrides.pop("on_exceed", "block"),
        **overrides,
    )
    db.add(row)
    await db.flush()
    return row


async def _notifications(db: AsyncSession, tenant_id, kind: str) -> list[Notification]:
    return list(
        (
            await db.execute(
                select(Notification).where(
                    Notification.tenant_id == tenant_id,
                    Notification.kind == kind,
                )
            )
        )
        .scalars()
        .all()
    )


# ------------------------------------------------------------------ soft tier --


async def test_crossing_the_soft_cap_warns_and_continues(db: AsyncSession, tenant_ctx, monkeypatch):
    await _policy(db, tenant_ctx.tenant_id, hard_cap="10", soft_cap="5", on_exceed="block")
    monkeypatch.setattr(budget_module, "_month_spend", _spend(Decimal("5.5")))
    monkeypatch.setattr(budget_module, "_reserved_spend", _spend(Decimal("0")))

    reservation_id = await reserve_budget(db, tenant_ctx.tenant_id, estimated_cost=Decimal("0.10"))

    assert reservation_id is not None, "the soft tier must warn, never stop usage"
    alerts = await _notifications(db, tenant_ctx.tenant_id, "ai_budget_soft_cap")
    assert len(alerts) == 1, "no renewal-asking warning was raised at the soft cap"
    assert "/settings/usage" in (alerts[0].action_url or "")
    assert "renew" in alerts[0].body.lower()


async def test_below_the_soft_cap_is_silent(db: AsyncSession, tenant_ctx, monkeypatch):
    await _policy(db, tenant_ctx.tenant_id, hard_cap="10", soft_cap="5", on_exceed="block")
    monkeypatch.setattr(budget_module, "_month_spend", _spend(Decimal("1")))
    monkeypatch.setattr(budget_module, "_reserved_spend", _spend(Decimal("0")))

    await reserve_budget(db, tenant_ctx.tenant_id, estimated_cost=Decimal("0.10"))

    assert await _notifications(db, tenant_ctx.tenant_id, "ai_budget_soft_cap") == []


async def test_the_soft_warning_fires_once_per_month(db: AsyncSession, tenant_ctx, monkeypatch):
    await _policy(db, tenant_ctx.tenant_id, hard_cap="10", soft_cap="5", on_exceed="block")
    monkeypatch.setattr(budget_module, "_month_spend", _spend(Decimal("6")))
    monkeypatch.setattr(budget_module, "_reserved_spend", _spend(Decimal("0")))

    for _ in range(3):
        await reserve_budget(db, tenant_ctx.tenant_id, estimated_cost=Decimal("0.10"))

    alerts = await _notifications(db, tenant_ctx.tenant_id, "ai_budget_soft_cap")
    assert len(alerts) == 1, f"dedup failed — {len(alerts)} soft warnings in one month"


async def test_an_agent_scoped_policy_never_raises_the_tenant_soft_warning(
    db: AsyncSession, tenant_ctx, monkeypatch
):
    """The soft tier is a subscription story: an agent-scoped cap (which
    governs one agent's own spend) must not page the tenant's owners."""
    from app.modules.ai.models import Agent

    tenant_id = tenant_ctx.tenant_id
    agent = Agent(
        tenant_id=tenant_id,
        kind="customer",
        name="Solo",
        model="fast",
        system_prompt="s",
        is_active=True,
    )
    db.add(agent)
    await db.flush()
    # Tenant scope: a plain cap with NO soft tier. Agent scope: soft_cap set.
    await _policy(db, tenant_id, hard_cap="100", on_exceed="block")
    db.add(
        BudgetPolicy(
            tenant_id=tenant_id,
            agent_id=agent.id,
            period="monthly",
            hard_cap=Decimal("10"),
            soft_cap=Decimal("5"),
            on_exceed="block",
        )
    )
    await db.flush()
    monkeypatch.setattr(budget_module, "_month_spend", _spend(Decimal("6")))
    monkeypatch.setattr(budget_module, "_reserved_spend", _spend(Decimal("0")))

    await reserve_budget(db, tenant_id, agent_id=agent.id, estimated_cost=Decimal("0.10"))

    assert await _notifications(db, tenant_id, "ai_budget_soft_cap") == []


# ------------------------------------------------------------------ hard tier --


async def test_crossing_the_hard_cap_stamps_the_durable_stop(
    db: AsyncSession, tenant_ctx, monkeypatch
):
    policy = await _policy(db, tenant_ctx.tenant_id, hard_cap="10", on_exceed="block")
    monkeypatch.setattr(budget_module, "_month_spend", _spend(Decimal("10")))
    monkeypatch.setattr(budget_module, "_reserved_spend", _spend(Decimal("0")))

    with pytest.raises(AIBudgetExhaustedError):
        await reserve_budget(db, tenant_ctx.tenant_id, estimated_cost=Decimal("1"))

    await db.refresh(policy)
    assert policy.hard_stopped_at is not None, "the block raise did not stamp the durable stop"


async def test_the_durable_stop_blocks_even_at_zero_spend(
    db: AsyncSession, tenant_ctx, monkeypatch
):
    policy = await _policy(db, tenant_ctx.tenant_id, hard_cap="10", on_exceed="block")
    policy.hard_stopped_at = datetime.now(UTC)
    await db.flush()
    monkeypatch.setattr(budget_module, "_month_spend", _spend(Decimal("0")))
    monkeypatch.setattr(budget_module, "_reserved_spend", _spend(Decimal("0")))

    with pytest.raises(AIBudgetExhaustedError, match="hard limit"):
        await reserve_budget(db, tenant_ctx.tenant_id, estimated_cost=Decimal("0.01"))


async def test_a_lifted_stop_is_honoured_and_never_re_stamps_in_the_same_period(
    db: AsyncSession, tenant_ctx, monkeypatch
):
    policy = await _policy(db, tenant_ctx.tenant_id, hard_cap="10", on_exceed="block")
    policy.hard_stopped_at = datetime.now(UTC)
    await db.flush()

    assert await lift_hard_stop(db, tenant_ctx.tenant_id) is True
    await db.refresh(policy)
    assert policy.hard_stopped_at is None
    assert policy.hard_stop_lifted_period == datetime.now(UTC).strftime("%Y-%m")

    # Back over the cap within the same period: refused by the ordinary cap
    # comparison, but NOT re-stamped — the lift must hold for the period.
    monkeypatch.setattr(budget_module, "_month_spend", _spend(Decimal("11")))
    monkeypatch.setattr(budget_module, "_reserved_spend", _spend(Decimal("0")))
    with pytest.raises(AIBudgetExhaustedError):
        await reserve_budget(db, tenant_ctx.tenant_id, estimated_cost=Decimal("1"))
    await db.refresh(policy)
    assert policy.hard_stopped_at is None, "the stop flip-flopped within the lifted period"


async def test_lift_with_no_stop_is_a_honest_no(db: AsyncSession, tenant_ctx) -> None:
    await _policy(db, tenant_ctx.tenant_id, hard_cap="10", on_exceed="block")
    assert await lift_hard_stop(db, tenant_ctx.tenant_id) is False


async def test_reactivation_dispatch_lifts_the_stop(db: AsyncSession, tenant_ctx) -> None:
    """The registered reactivation hook is the automatic 'renewal' moment."""
    import app.modules.ai.core.provisioning  # noqa: F401 — registers the hook

    assert tenant_reactivated_hooks(), "no reactivation hook is registered by the ai module"

    policy = await _policy(db, tenant_ctx.tenant_id, hard_cap="10", on_exceed="block")
    policy.hard_stopped_at = datetime.now(UTC)
    await db.flush()

    await dispatch_tenant_reactivated_hooks(db, tenant_ctx.tenant_id)

    await db.refresh(policy)
    assert policy.hard_stopped_at is None, "reactivation did not lift the AI hard stop"
    assert policy.hard_stop_lifted_period == datetime.now(UTC).strftime("%Y-%m")


def test_the_fallback_retry_catches_a_second_budget_refusal() -> None:
    """The fallback retry re-enters reserve_budget, which re-raises
    AIBudgetFallbackRequested for the same exhausted cap. Without a catch
    INSIDE the handler, the second raise escapes as a generic run error and
    the message dead-letters instead of handing over (review finding)."""
    import ast
    import pathlib

    import app.modules.ai.runtime as runtime_module

    tree = ast.parse(pathlib.Path(runtime_module.__file__).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler) and "AIBudgetFallbackRequested" in ast.dump(
            node.type
        ):
            # Walk the WHOLE handler body: the retry try may sit anywhere in
            # it, and the guard is that a nested try catches the same
            # exception the second time the budget refuses.
            inner_handlers = [
                h
                for stmt in ast.walk(ast.Module(body=node.body, type_ignores=[]))
                if isinstance(stmt, ast.Try)
                for h in stmt.handlers
                if "AIBudgetFallbackRequested" in ast.dump(h.type)
            ]
            if inner_handlers:
                return  # the retry path handles the second refusal
    raise AssertionError(
        "the fallback retry no longer catches a second AIBudgetFallbackRequested — "
        "an exhausted fallback tier dead-letters instead of handing over"
    )
