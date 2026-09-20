"""AI gateway — model routing, cost recording and monthly budget enforcement.

Reads the tenant's ``model_configs`` row for the requested alias and falls back
to the deployment-wide primary provider settings. Every call writes a
``model_calls`` row (tokens, latency, cost estimate). The gateway NEVER
commits — it flushes inside the caller's transaction.

NOTE: settings fields ``ai_provider_primary`` / ``ai_api_key_primary`` /
``ai_base_url_primary`` are read defensively via ``getattr``; they are optional
deployment settings and are intentionally NOT added to app/core/config.py.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import RateLimitExceededError, ValidationError
from app.modules.ai.models import AIUsage, ModelCall, ModelConfig
from app.modules.ai.providers import AIProvider, ChatCompletionResult, EmbeddingProvider

# Monthly AI spend cap per tenant (USD, estimated) — deliberately a constant.
MONTHLY_BUDGET_CAP = 50.0

# Flat per-token estimates, used when a tenant has no per-model pricing row.
# Both DIRECTIONS are priced: charging only output under-counts real spend,
# because the prompt (history + knowledge + tools) is usually the larger half
# of the tokens on a conversational turn.
_COST_PER_INPUT_TOKEN = Decimal("0.0000005")   # $0.50 / 1M tokens
_COST_PER_OUTPUT_TOKEN = Decimal("0.000002")   # $2.00 / 1M tokens

# How long a reservation is held before a sweep may reclaim it. A run that
# crashes between reserve and settle must not hold budget forever.
RESERVATION_TTL_MINUTES = 30

ALIASES = frozenset({"fast", "strong", "cheap", "embedding", "fallback"})

_CENT = Decimal("0.00000001")


def estimate_cost(tokens_in: int, tokens_out: int) -> Decimal:
    """Exact cost of a call, in Decimal.

    Returns Decimal rather than float on purpose: the column is Numeric(18,8)
    and float arithmetic would reintroduce exactly the rounding the column was
    widened to avoid (a float cost of 0.001 was being stored as 0.00, so the
    monthly total was always zero and the hard cap was unenforceable).
    """
    total = (
        Decimal(max(int(tokens_in or 0), 0)) * _COST_PER_INPUT_TOKEN
        + Decimal(max(int(tokens_out or 0), 0)) * _COST_PER_OUTPUT_TOKEN
    )
    return total.quantize(_CENT)


async def resolve_model_config(
    session: AsyncSession, tenant_id: UUID, alias: str
) -> dict[str, Any]:
    """Resolve alias -> provider config (tenant model_configs row, then settings).

    Returns {"provider", "model", "base_url", "api_key"}.
    """
    if alias not in ALIASES:
        raise ValidationError(f"unknown model alias: {alias}")

    row = (
        await session.execute(
            select(ModelConfig).where(
                ModelConfig.tenant_id == tenant_id,
                ModelConfig.alias == alias,
                ModelConfig.is_active.is_(True),
            )
        )
    ).scalar_one_or_none()
    if row is not None:
        config = dict(row.config or {})
        return {
            "provider": row.provider,
            "model": row.model,
            "base_url": str(config.get("base_url") or ""),
            "api_key": str(config.get("api_key") or ""),
            "extra": config,
        }

    settings = get_settings()
    provider = getattr(settings, "ai_provider_primary", "") or ""
    if not provider:
        raise ValidationError(f"no model configured for alias {alias}")
    return {
        "provider": provider,
        "model": getattr(settings, "ai_model_primary", "") or provider,
        "base_url": getattr(settings, "ai_base_url_primary", "") or "",
        "api_key": getattr(settings, "ai_api_key_primary", "") or "",
    }


async def _month_spend(session: AsyncSession, tenant_id: UUID) -> Decimal:
    """Sum of ai_usage cost for the current calendar month, for this tenant."""
    month_start = datetime.now(UTC).date().replace(day=1)
    total = (
        await session.execute(
            select(func.coalesce(func.sum(AIUsage.cost), 0)).where(
                AIUsage.tenant_id == tenant_id,
                AIUsage.period_date >= month_start,
            )
        )
    ).scalar_one()
    return Decimal(total or 0)


async def _reserved_spend(session: AsyncSession, tenant_id: UUID) -> Decimal:
    """Budget already committed to in-flight runs (not yet settled)."""
    from app.modules.ai.models import AIBudgetReservation

    total = (
        await session.execute(
            select(func.coalesce(func.sum(AIBudgetReservation.amount), 0)).where(
                AIBudgetReservation.tenant_id == tenant_id,
                AIBudgetReservation.status == "active",
                AIBudgetReservation.expires_at > datetime.now(UTC),
            )
        )
    ).scalar_one()
    return Decimal(total or 0)


async def expire_stale_reservations(
    session: AsyncSession, tenant_id: UUID, *, now: datetime | None = None
) -> int:
    """Release reservations held by runs that never settled (crash/restart)."""
    from sqlalchemy import update

    from app.modules.ai.models import AIBudgetReservation

    result = await session.execute(
        update(AIBudgetReservation)
        .where(
            AIBudgetReservation.tenant_id == tenant_id,
            AIBudgetReservation.status == "active",
            AIBudgetReservation.expires_at <= (now or datetime.now(UTC)),
        )
        .values(status="expired")
    )
    return result.rowcount or 0


async def settle_reservation(
    session: AsyncSession,
    reservation_id: UUID | None,
    *,
    now: datetime | None = None,
) -> None:
    """Mark a reservation settled once its run has finished (success or not)."""
    if reservation_id is None:
        return
    from sqlalchemy import update

    from app.modules.ai.models import AIBudgetReservation

    await session.execute(
        update(AIBudgetReservation)
        .where(
            AIBudgetReservation.id == reservation_id,
            AIBudgetReservation.status == "active",
        )
        .values(status="settled", settled_at=now or datetime.now(UTC))
    )


def _resolve_cap(policies: list, agent_id: UUID | None) -> tuple[Decimal, str]:
    """Agent-scoped policy wins over tenant-scoped; falls back to the constant."""
    for scope_policy in policies:
        if scope_policy.agent_id is not None and scope_policy.agent_id != agent_id:
            continue
        return Decimal(scope_policy.hard_cap), scope_policy.on_exceed
    return Decimal(MONTHLY_BUDGET_CAP), "block"


async def reserve_budget(
    session: AsyncSession,
    tenant_id: UUID,
    *,
    agent_id: UUID | None = None,
    estimated_cost: Decimal | float = 0,
) -> UUID | None:
    """Spec §42 reserve half: take budget BEFORE the provider call.

    A preflight that only reads the spend so far lets N concurrent runs pass the
    same check and all spend, so the cap is overshot by the concurrency factor.
    Committing a reservation up front is what makes the cap hold under load.

    Returns the reservation id to settle afterwards, or None when the tenant has
    no cap (`on_exceed` is not "block" or the cap is zero/unset).
    """
    from sqlalchemy import select as sa_select

    from app.modules.ai.models import AIBudgetReservation, BudgetPolicy

    policies = (
        await session.execute(
            sa_select(BudgetPolicy)
            .where(
                BudgetPolicy.tenant_id == tenant_id,
                BudgetPolicy.period == "monthly",
            )
            # agent-specific policies win over tenant-level ones
            .order_by(BudgetPolicy.agent_id.is_(None))
        )
    ).scalars().all()
    cap, on_exceed = _resolve_cap(list(policies), agent_id)

    if cap <= 0 or on_exceed != "block":
        return None

    spend = await _month_spend(session, tenant_id)
    reserved = await _reserved_spend(session, tenant_id)
    estimate = Decimal(str(estimated_cost or 0))
    committed = spend + reserved

    if committed + estimate >= cap:
        raise RateLimitExceededError(
            "monthly AI budget exceeded",
            details={
                "spend": str(spend),
                "reserved": str(reserved),
                "cap": str(cap),
            },
        )

    reservation = AIBudgetReservation(
        tenant_id=tenant_id,
        agent_id=agent_id,
        amount=estimate,
        status="active",
        expires_at=datetime.now(UTC) + timedelta(minutes=RESERVATION_TTL_MINUTES),
    )
    session.add(reservation)
    await session.flush()
    return reservation.id


async def enforce_budget(
    session: AsyncSession, tenant_id: UUID, *, agent_id: UUID | None = None
) -> dict:
    """Read-only budget view (spend, cap, ratio) without taking a reservation.

    Kept for callers that only want to report; `reserve_budget` is what a
    spending path must call, because only it actually holds the budget.
    """
    from sqlalchemy import select as sa_select

    from app.modules.ai.models import BudgetPolicy

    policies = (
        await session.execute(
            sa_select(BudgetPolicy)
            .where(
                BudgetPolicy.tenant_id == tenant_id,
                BudgetPolicy.period == "monthly",
            )
            .order_by(BudgetPolicy.agent_id.is_(None))
        )
    ).scalars().all()
    cap, on_exceed = _resolve_cap(list(policies), agent_id)

    spend = await _month_spend(session, tenant_id)
    ratio = float(spend / cap * 100) if cap > 0 else 0.0
    if spend >= cap and on_exceed == "block":
        raise RateLimitExceededError(
            "monthly AI budget exceeded",
            details={"spend": str(spend), "cap": str(cap)},
        )
    return {
        "spend": float(spend),
        "cap": float(cap),
        "ratio": ratio,
        "on_exceed": on_exceed,
    }


class AIGateway:
    """Single entry point for model calls — resolves config, records spend."""

    def __init__(self, provider: AIProvider | None = None) -> None:
        self._provider = provider or AIProvider()
        self._embeddings = EmbeddingProvider()

    async def chat(
        self,
        session: AsyncSession,
        tenant_id: UUID,
        *,
        alias: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        agent_id: UUID | None = None,
        run_id: UUID | None = None,
        _client: Any | None = None,
    ) -> ChatCompletionResult:
        config = await resolve_model_config(session, tenant_id, alias)
        # §42 reserve: hold budget BEFORE the provider call so concurrent runs
        # cannot all pass the same read-only preflight and overshoot the cap.
        # A rough upper bound (max_tokens output + a prompt allowance) is
        # reserved and the real cost is recorded when the call returns.
        estimated = estimate_cost(
            tokens_in=len(str(messages)) // 4,  # ~4 chars per token
            tokens_out=max_tokens or 1024,
        )
        reservation_id = await reserve_budget(
            session, tenant_id, agent_id=agent_id, estimated_cost=estimated
        )

        started = time.perf_counter()
        status = "ok"
        result: ChatCompletionResult | None = None
        try:
            result = await self._provider.chat(
                base_url=config["base_url"],
                api_key=config["api_key"],
                model=config["model"],
                messages=messages,
                tools=tools,
                temperature=temperature,
                max_tokens=max_tokens,
                _client=_client,
            )
            return result
        except Exception:
            status = "error"
            raise
        finally:
            latency_ms = int((time.perf_counter() - started) * 1000)
            tokens_in = result.tokens_in if result else 0
            tokens_out = result.tokens_out if result else 0
            session.add(
                ModelCall(
                    tenant_id=tenant_id,
                    run_id=run_id,
                    alias=alias,
                    provider=config["provider"],
                    model=config["model"],
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    # BOTH directions are priced: charging only output
                    # under-counted spend, because the prompt is usually the
                    # larger half of a conversational turn.
                    cost=estimate_cost(tokens_in, tokens_out) if result else Decimal(0),
                    latency_ms=latency_ms,
                    status=status,
                )
            )
            # §42 settle: release the hold whether the call succeeded or not —
            # a failed call must not hold budget until its TTL expires.
            await settle_reservation(session, reservation_id)
            await session.flush()

    async def embed(
        self,
        session: AsyncSession,
        tenant_id: UUID,
        *,
        texts: list[str],
        run_id: UUID | None = None,
        _client: Any | None = None,
    ) -> list[list[float]]:
        """Embed texts through the tenant's 'embedding' alias (recorded too)."""
        await enforce_budget(session, tenant_id)
        config = await resolve_model_config(session, tenant_id, "embedding")

        started = time.perf_counter()
        status = "ok"
        vectors: list[list[float]] = []
        try:
            vectors = await self._embeddings.embed(
                base_url=config["base_url"],
                api_key=config["api_key"],
                model=config["model"],
                texts=texts,
                dimensions=(config.get("extra") or {}).get("dimensions"),
                _client=_client,
            )
            return vectors
        except Exception:
            status = "error"
            raise
        finally:
            latency_ms = int((time.perf_counter() - started) * 1000)
            session.add(
                ModelCall(
                    tenant_id=tenant_id,
                    run_id=run_id,
                    alias="embedding",
                    provider=config["provider"],
                    model=config["model"],
                    tokens_in=0,
                    tokens_out=0,
                    cost=0.0,
                    latency_ms=latency_ms,
                    status=status,
                )
            )
            await session.flush()
