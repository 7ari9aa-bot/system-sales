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
from datetime import UTC, datetime
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

# Flat output-token cost estimate used for model_calls / ai_usage rollups.
_COST_PER_OUTPUT_TOKEN = 0.000002

ALIASES = frozenset({"fast", "strong", "cheap", "embedding", "fallback"})


def estimate_cost(tokens_out: int) -> float:
    """Cost estimate for a response; stored as MONEY (2 decimals) in the DB."""
    return float(round(tokens_out * _COST_PER_OUTPUT_TOKEN, 6))


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


async def _month_spend(session: AsyncSession, tenant_id: UUID) -> float:
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
    return float(total)


async def enforce_budget(
    session: AsyncSession, tenant_id: UUID, *, agent_id: UUID | None = None
) -> dict:
    """Spec §42: per-tenant/agent budget preflight (reserve/settle pattern).

    Resolves BudgetPolicy (agent-scope first, then tenant-scope, then the
    MONTHLY_BUDGET_CAP default); returns policy context. Threshold crossings
    are surfaced via the returned dict (warning emitted by the caller).
    """
    spend = await _month_spend(session, tenant_id)
    cap = MONTHLY_BUDGET_CAP
    on_exceed = "block"

    from sqlalchemy import select as sa_select

    from app.modules.ai.models import BudgetPolicy

    for scope_policy in (
        await session.execute(
            sa_select(BudgetPolicy)
            .where(
                BudgetPolicy.tenant_id == tenant_id,
                BudgetPolicy.period == "monthly",
            )
            # agent-specific policies win over tenant-level ones
            .order_by(BudgetPolicy.agent_id.is_(None))
        )
    ).scalars().all():
        if scope_policy.agent_id is not None and scope_policy.agent_id != agent_id:
            continue
        cap = float(scope_policy.hard_cap)
        on_exceed = scope_policy.on_exceed
        break

    ratio = (spend / cap * 100) if cap > 0 else 0.0
    if spend >= cap and on_exceed == "block":
        raise RateLimitExceededError(
            "monthly AI budget exceeded",
            details={"spend": spend, "cap": cap},
        )
    return {"spend": spend, "cap": cap, "ratio": ratio, "on_exceed": on_exceed}


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
        await enforce_budget(session, tenant_id)
        config = await resolve_model_config(session, tenant_id, alias)

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
            session.add(
                ModelCall(
                    tenant_id=tenant_id,
                    run_id=run_id,
                    alias=alias,
                    provider=config["provider"],
                    model=config["model"],
                    tokens_in=result.tokens_in if result else 0,
                    tokens_out=result.tokens_out if result else 0,
                    cost=estimate_cost(result.tokens_out) if result else 0.0,
                    latency_ms=latency_ms,
                    status=status,
                )
            )
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
