"""AI gateway — model routing, cost recording and monthly budget enforcement.

Reads the tenant's ``model_configs`` row for the requested alias and falls back
to the deployment-wide primary provider settings. Every call writes a
``model_calls`` row (tokens, latency, cost estimate). The gateway NEVER
commits — it flushes inside the caller's transaction.

The deployment-wide primary provider is configured by ``AI_PROVIDER_PRIMARY``
/ ``AI_MODEL_PRIMARY`` / ``AI_BASE_URL_PRIMARY`` / ``AI_API_KEY_PRIMARY``, all
declared in ``app/core/config.py``. The model name is read as a declared field,
not through ``getattr``: a missing field used to degrade the request to
``model="openai"`` (the provider name), and ``extra="ignore"`` swallowed the
env var, so the misconfiguration was invisible until the provider returned a
400 that no tenant could attribute to configuration.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.circuit_breaker import PROVIDER_AI, get_breaker
from app.core.config import get_settings
from app.core.errors import RateLimitExceededError, ValidationError
from app.modules.ai.models import AIUsage, ModelCall, ModelConfig
from app.modules.ai.providers import AIProvider, ChatCompletionResult, EmbeddingProvider

logger = logging.getLogger(__name__)

# Monthly AI spend cap per tenant (USD, estimated) — the fallback when a tenant
# has no BudgetPolicy row. Read from settings so a deployment can raise or lower
# it without a code change; the default keeps the previous behaviour exactly.
MONTHLY_BUDGET_CAP = 50.0

# §42: the thresholds an operator must hear about BEFORE the cap bites.
# `BudgetPolicy.warning_threshold` existed on the model and was never read, so
# no alert was raised at any percentage — a tenant could hit the hard cap with
# no warning at all.
BUDGET_ALERT_THRESHOLDS: tuple[int, ...] = (50, 80, 90, 100)

# Flat per-token estimates, used when a tenant has no per-model pricing row.
# Both DIRECTIONS are priced: charging only output under-counts real spend,
# because the prompt (history + knowledge + tools) is usually the larger half
# of the tokens on a conversational turn.
_COST_PER_INPUT_TOKEN = Decimal("0.0000005")  # $0.50 / 1M tokens
_COST_PER_OUTPUT_TOKEN = Decimal("0.000002")  # $2.00 / 1M tokens

# How long a reservation is held before a sweep may reclaim it. A run that
# crashes between reserve and settle must not hold budget forever.
RESERVATION_TTL_MINUTES = 30

ALIASES = frozenset({"fast", "strong", "cheap", "embedding", "fallback"})

# §43: PII redaction patterns. Applied to message content before sending to
# an external AI provider when the tenant's AIProviderPolicy has
# pii_redaction_required=True. The redactor is deliberately conservative — it
# masks anything that looks like PII rather than attempting perfect detection,
# because a false negative leaks PII while a false positive only degrades
# the model's context.
_PII_PATTERNS: list[tuple[str, str]] = [
    # Email addresses
    (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"), "[REDACTED_EMAIL]"),
    # Phone numbers: international (+966...) and local (05...)
    (re.compile(r"\+?\d[\d\s\-()]{7,}\d"), "[REDACTED_PHONE]"),
    # Saudi national ID (10 digits)
    (re.compile(r"\b[1-2]\d{9}\b"), "[REDACTED_ID]"),
    # Credit card numbers (13-19 digits, with optional separators)
    (re.compile(r"\b(?:\d[ -]*?){13,19}\b"), "[REDACTED_CARD]"),
]


def _redact_pii(messages: list[dict]) -> list[dict]:
    """§43: mask PII in message content before sending to an AI provider.

    Returns a NEW list (does not mutate the input). Only the ``content``
    field of role=user/assistant/system messages is scanned; tool_call
    arguments and tool results are left as-is (they are server-side bound
    and already tenant-scoped by §132).
    """
    redacted: list[dict] = []
    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content")
        if role in ("user", "assistant", "system") and isinstance(content, str):
            for pattern, replacement in _PII_PATTERNS:
                content = pattern.sub(replacement, content)
            redacted.append({**msg, "content": content})
        else:
            redacted.append(msg)
    return redacted


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
    model = getattr(settings, "ai_model_primary", "") or ""
    if not model:
        # Never fall back to the provider name: an OpenAI-compatible endpoint
        # rejects `model="openai"`, and the operator needs to hear WHICH knob
        # is missing rather than debug a tenant's chat failures.
        raise ValidationError(
            f"no model name configured for alias {alias}: set AI_MODEL_PRIMARY "
            "or add a model_configs row for this tenant"
        )
    return {
        "provider": provider,
        "model": model,
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


async def _day_spend(session: AsyncSession, tenant_id: UUID) -> Decimal:
    """§42: sum of ai_usage cost for today (UTC), for this tenant."""
    today = datetime.now(UTC).date()
    total = (
        await session.execute(
            select(func.coalesce(func.sum(AIUsage.cost), 0)).where(
                AIUsage.tenant_id == tenant_id,
                AIUsage.period_date == today,
            )
        )
    ).scalar_one()
    return Decimal(total or 0)


def _daily_cap(monthly_cap: Decimal) -> Decimal:
    """§42: the daily cost cap — defaults to monthly_cap / 30."""
    if monthly_cap <= 0:
        return Decimal(0)
    return (monthly_cap / Decimal(30)).quantize(Decimal("0.01"))


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


def _default_cap() -> Decimal:
    """The deployment's default monthly cap when a tenant has no policy row.

    Read from settings so the ceiling can be changed without a deploy; the
    setting's default preserves the previous constant exactly.
    """
    configured = getattr(get_settings(), "ai_monthly_budget_cap_default", MONTHLY_BUDGET_CAP)
    try:
        return Decimal(str(configured))
    except (ArithmeticError, ValueError):
        return Decimal(str(MONTHLY_BUDGET_CAP))


def _resolve_cap(policies: list, agent_id: UUID | None) -> tuple[Decimal, str]:
    """Agent-scoped policy wins over tenant-scoped; falls back to the default.

    "No policy" must never mean "no limit": a tenant without a BudgetPolicy row
    still gets the deployment default, so a misconfigured (or never-configured)
    tenant cannot spend without bound.
    """
    for scope_policy in policies:
        if scope_policy.agent_id is not None and scope_policy.agent_id != agent_id:
            continue
        return Decimal(scope_policy.hard_cap), scope_policy.on_exceed
    return _default_cap(), "block"


async def _raise_budget_alerts(
    session: AsyncSession,
    tenant_id: UUID,
    *,
    cap: Decimal,
    committed: Decimal,
) -> None:
    """Notify the tenant's owners when spend crosses a §42 threshold.

    `BudgetPolicy.warning_threshold` was on the model and never read, so a
    tenant could reach the hard cap with no warning at all. Each threshold
    notifies once per calendar month: the notification carries a per-period
    dedup key, so a reserve that happens 500 times above 80% still produces one
    alert.
    """
    if cap <= 0:
        return
    ratio = (committed / cap) * Decimal(100)
    crossed = [threshold for threshold in BUDGET_ALERT_THRESHOLDS if ratio >= threshold]
    if not crossed:
        return
    threshold = max(crossed)

    from app.modules.notifications.service import NotificationService

    # Owner lookup via SQL rather than `identity.models`.
    #
    # `identity` already imports `ai` (ai/hooks uses the entitlement service),
    # so importing its models here would close a NEW ai <-> identity import
    # cycle — which tests/test_module_boundaries.py fails on. The query is two
    # joins over tenant-scoped tables and runs under the tenant GUC, so it is
    # exactly as safe as the ORM version, without the coupling.
    owner_ids = (
        (
            await session.execute(
                text(
                    "SELECT tu.user_id FROM tenant_users tu "
                    "JOIN roles r ON r.id = tu.role_id "
                    "WHERE tu.tenant_id = :tenant_id AND r.code = 'owner'"
                ),
                {"tenant_id": str(tenant_id)},
            )
        )
        .scalars()
        .all()
    )
    if not owner_ids:
        return

    period_key = datetime.now(UTC).strftime("%Y-%m")
    for owner_id in owner_ids:
        await NotificationService.create(
            session,
            tenant_id,
            owner_id,
            kind="ai_budget_threshold",
            title="AI budget threshold reached",
            body=(f"AI spend has reached {ratio:.0f}% of the monthly cap ({committed} of {cap})."),
            payload={
                "threshold": threshold,
                "ratio": str(ratio.quantize(Decimal("0.01"))),
                "cap": str(cap),
                "committed": str(committed),
                "period": period_key,
            },
            dedup_key=f"ai_budget:{tenant_id}:{period_key}:{threshold}",
        )


class AIBudgetFallbackRequested(Exception):
    """§42: the cap is exhausted and the policy says DOWNGRADE, not die.

    Raised instead of RateLimitExceededError when BudgetPolicy.on_exceed ==
    "fallback". The runner catches it and retries the same step on the
    "fallback" alias; if the fallback alias is the one that just failed it
    hands the conversation to a human instead of looping.
    """

    def __init__(self, message: str, *, details: dict | None = None) -> None:
        super().__init__(message)
        self.details = details or {}


class AIBudgetExhaustedError(RateLimitExceededError):
    """§42: a spend ceiling was reached — monthly cap, daily cap or fairness.

    Distinct from a generic rate limit so the auto-reply hook can turn it into
    a human handover. Before this existed the two ceilings failed differently
    and both ended in silence: the fairness gate raised ``ValidationError``,
    which the worker classifies as PERMANENT and dead-letters on the spot, and
    the cost cap raised a bare ``RateLimitExceededError``, which burned five
    retries against a ceiling that cannot rise, then dead-lettered too. Neither
    path told a human the customer was waiting.

    Subclasses ``RateLimitExceededError`` so every existing handler — the 429
    mapping, ``transcribe_inbound_voice``'s budget guard — keeps working.
    """

    code = "ai_budget_exhausted"
    # Retrying inside the same period cannot succeed; the ceiling resets on its
    # own schedule (daily fairness / monthly cap), not on a backoff.
    retryable = False


def _on_budget_exceeded(on_exceed: str, message: str, *, details: dict) -> None:
    """§42 mode dispatch when committed spend crosses the cap."""
    if on_exceed == "fallback":
        raise AIBudgetFallbackRequested(message, details=details)
    if on_exceed == "warn":
        # Alert-and-allow: the tenant explicitly chose overrun-with-warning.
        # The reservation is still taken and settled, so spend stays accounted.
        logger.warning("ai.budget_exceeded_warn %s %s", message, details)
        return
    raise AIBudgetExhaustedError(message, details=details)


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
    no cap (the cap is zero/unset). The cap is enforced for EVERY on_exceed
    mode — "warn" allows the call but alerts, "fallback" raises
    AIBudgetFallbackRequested so the runner can downgrade to the cheaper
    model, "block" raises RateLimitExceededError. A mode NEVER disables the
    cap itself (§42: the hard cap exists to stop runaway spend).
    """
    from sqlalchemy import select as sa_select

    from app.modules.ai.models import AIBudgetReservation, BudgetPolicy

    policies = (
        (
            await session.execute(
                sa_select(BudgetPolicy)
                .where(
                    BudgetPolicy.tenant_id == tenant_id,
                    BudgetPolicy.period == "monthly",
                )
                # agent-specific policies win over tenant-level ones
                .order_by(BudgetPolicy.agent_id.is_(None))
            )
        )
        .scalars()
        .all()
    )
    cap, on_exceed = _resolve_cap(list(policies), agent_id)

    if cap <= 0:
        return None

    spend = await _month_spend(session, tenant_id)
    reserved = await _reserved_spend(session, tenant_id)
    estimate = Decimal(str(estimated_cost or 0))
    committed = spend + reserved

    # §42: warn before the cap blocks a customer-facing reply. Checked on the
    # COMMITTED spend (already spent + held), so the alert reflects what the
    # tenant is actually on the hook for.
    await _raise_budget_alerts(session, tenant_id, cap=cap, committed=committed)

    # §42: daily cost cap — prevents a single day from burning the entire
    # monthly budget. Defaults to monthly_cap / 30.
    day_spend = await _day_spend(session, tenant_id)
    daily_cap = _daily_cap(cap)
    if committed + estimate >= cap:
        _on_budget_exceeded(
            on_exceed,
            "monthly AI budget exceeded",
            details={
                "spend": str(spend),
                "reserved": str(reserved),
                "cap": str(cap),
            },
        )

    if daily_cap > 0 and day_spend + estimate >= daily_cap:
        _on_budget_exceeded(
            on_exceed,
            "daily AI budget exceeded",
            details={
                "day_spend": str(day_spend),
                "daily_cap": str(daily_cap),
                "estimate": str(estimate),
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
        (
            await session.execute(
                sa_select(BudgetPolicy)
                .where(
                    BudgetPolicy.tenant_id == tenant_id,
                    BudgetPolicy.period == "monthly",
                )
                .order_by(BudgetPolicy.agent_id.is_(None))
            )
        )
        .scalars()
        .all()
    )
    cap, on_exceed = _resolve_cap(list(policies), agent_id)

    spend = await _month_spend(session, tenant_id)
    ratio = float(spend / cap * 100) if cap > 0 else 0.0
    if spend >= cap and on_exceed == "block":
        raise AIBudgetExhaustedError(
            "monthly AI budget exceeded",
            details={"spend": str(spend), "cap": str(cap)},
        )
    return {
        # §47/ADR-053: spend and cap are AMOUNTS, so they cross JSON as
        # `str(Decimal)` — the same spelling the budget-exceeded path one frame
        # above uses. `ratio` is a percentage and stays a number. `str()` rather
        # than marketing's `wire_money`: AI money is `Numeric(18,8)` and the
        # two-place quantise would zero a sub-cent spend out.
        "spend": str(spend),
        "cap": str(cap),
        "ratio": ratio,
        "on_exceed": on_exceed,
    }


class AIGateway:
    """Single entry point for model calls — resolves config, records spend."""

    def __init__(self, provider: AIProvider | None = None) -> None:
        self._provider = provider or AIProvider()
        self._embeddings = EmbeddingProvider()

    def _provider_breaker(self, config: dict[str, Any]):
        """The breaker for THIS provider endpoint — not for all providers at once.

        §47 first wired the chat request behind the process-wide ``provider.ai``
        breaker, which named ONE breaker for every provider on the platform: a
        tenant's self-hosted or misconfigured endpoint failing repeatedly opened
        that single breaker and blocked every OTHER tenant's calls to completely
        different providers — one bad endpoint became a platform-wide AI outage,
        the opposite of the degradation-not-catastrophe goal. The breaker name is
        therefore scoped to the endpoint's HOST: every tenant of the same
        upstream (api.openai.com) still backs off together, because that IS one
        downstream dependency, while a dead private endpoint cannot reach across
        the network boundary to anyone else. Host, not URL: path/query noise
        must not fragment one provider into N breakers (N failures before any
        backoff is the bug the registry exists to prevent).
        """
        host = (urlsplit(config.get("base_url") or "").hostname or "").lower()
        return get_breaker(f"{PROVIDER_AI}:{host or 'unspecified'}")

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
        # §42 reserve: hold budget BEFORE anything else, so a run that cannot
        # afford to proceed fails fast (and before config resolution, which is
        # the order callers already rely on). Reserving up front is also what
        # stops N concurrent runs from all passing the same read-only preflight
        # and overshooting the cap.
        estimated = estimate_cost(
            tokens_in=len(str(messages)) // 4,  # ~4 chars per token
            tokens_out=max_tokens or 1024,
        )
        reservation_id = await reserve_budget(
            session, tenant_id, agent_id=agent_id, estimated_cost=estimated
        )

        # ── Everything below MUST settle the reservation, even if a pre-send
        #    gate (fairness, egress policy) rejects the call.  A single outer
        #    try…finally guarantees settle_reservation runs.
        started = time.perf_counter()
        status = "ok"
        result: ChatCompletionResult | None = None
        config: dict | None = None
        try:
            config = await resolve_model_config(session, tenant_id, alias)

            # §144: tenant fairness budget — a single tenant's AI consumption
            # must not starve the rest of the platform. This is a token-level
            # gate (estimated tokens), separate from the cost-level gate (§42)
            # which is about money.
            from app.core.fairness import ResourceType
            from app.core.fairness import consume as consume_fairness

            fairness_ok = await consume_fairness(
                tenant_id,
                ResourceType.AI_TOKENS,
                units=(len(str(messages)) // 4) + (max_tokens or 1024),
            )
            if not fairness_ok:
                # Deliberately NOT a ValidationError: the worker treats that as
                # a permanent failure and dead-letters the customer's message
                # immediately. A spent fairness budget is a spend ceiling, and
                # the auto-reply hook turns it into a human handover.
                raise AIBudgetExhaustedError(
                    "tenant AI token fairness budget exhausted — daily limit reached"
                )

            # §43: data-egress policy — is this tenant allowed to send data to
            # this provider/model? This is NOT authorization (the entitlement
            # check already happened); it is a DATA-CLASSIFICATION gate. A
            # provider with no policy row is allowed (fail-open; see policy.py).
            #
            # The spec's pre-send order is honored literally:
            # Classify → Redact where required → Apply policy → Send. Redaction
            # can downgrade the class (masked PII is no longer restricted), so
            # the gate is evaluated with the class the payload actually has when
            # it would leave this process.
            from app.modules.ai.policy import AIProviderPolicyService, classify_data

            region = str((config.get("extra") or {}).get("region") or "")
            data_class = classify_data(messages)
            egress_decision = await AIProviderPolicyService.evaluate(
                session,
                tenant_id,
                provider=config["provider"],
                model=config["model"],
                data_class=data_class,
                region=region or None,
            )
            if egress_decision.redact_required:
                # §43: actually redact PII before sending to the provider.
                messages = _redact_pii(messages)
                data_class = classify_data(messages)
                egress_decision = await AIProviderPolicyService.evaluate(
                    session,
                    tenant_id,
                    provider=config["provider"],
                    model=config["model"],
                    data_class=data_class,
                    region=region or None,
                )
                logger.info(
                    "ai.provider_redaction_applied tenant=%s provider=%s",
                    tenant_id,
                    config["provider"],
                )
            if not egress_decision.allowed:
                raise ValidationError(
                    f"AI provider blocked by data-egress policy: {egress_decision.reason}"
                )

            # §47: the ONE provider HTTP request goes through the breaker for
            # THIS provider endpoint (see _provider_breaker), so a dead or slow
            # provider is backed off instead of hammered — and its failure does
            # not stop a different provider.
            #
            # CircuitOpenError is a DomainError and is re-raised unchanged by the
            # handler below, so an open breaker stays visible as an open breaker.
            result = await self._provider_breaker(config).call(
                self._provider.chat,
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
                    provider=(config["provider"] if config else "unknown"),
                    model=(config["model"] if config else "unknown"),
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    cost=estimate_cost(tokens_in, tokens_out) if result else Decimal(0),
                    latency_ms=latency_ms,
                    status=status,
                )
            )
            # §42 settle (P1-2): release the hold whether the call succeeded or not —
            # a failed or cancelled call must not hold budget until its TTL expires.
            # Shielded against asyncio.wait_for cancellation so the hold is always released.
            try:
                await asyncio.shield(settle_reservation(session, reservation_id))
                await asyncio.shield(session.flush())
            except Exception:
                logger.warning(
                    "ai.settle_reservation_failed reservation=%s",
                    reservation_id,
                    exc_info=True,
                )

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

        # §43: data-egress policy on the embedding path too — embeddings
        # carry customer text to a provider, so the same gate applies (same
        # Classify → Redact → Apply order as chat).
        from app.modules.ai.policy import AIProviderPolicyService, classify_data

        region = str((config.get("extra") or {}).get("region") or "")
        data_class = classify_data(texts)
        egress_decision = await AIProviderPolicyService.evaluate(
            session,
            tenant_id,
            provider=config["provider"],
            model=config["model"],
            data_class=data_class,
            region=region or None,
        )
        if egress_decision.redact_required:
            # §43: redact PII in embedding texts too — embeddings carry
            # customer text to a provider, so the same gate applies.
            texts = [_redact_pii([{"role": "user", "content": t}])[0]["content"] for t in texts]
            data_class = classify_data(texts)
            egress_decision = await AIProviderPolicyService.evaluate(
                session,
                tenant_id,
                provider=config["provider"],
                model=config["model"],
                data_class=data_class,
                region=region or None,
            )
        if not egress_decision.allowed:
            raise ValidationError(
                f"AI embedding provider blocked by data-egress policy: {egress_decision.reason}"
            )

        started = time.perf_counter()
        status = "ok"
        vectors: list[list[float]] = []
        try:
            # §47: embeddings hit the SAME provider as chat, so they spend the
            # SAME per-endpoint breaker (see _provider_breaker). Wrapping only
            # `chat` left a dead provider reachable through the embedding path —
            # it would be hammered there while the chat breaker sat open.
            vectors = await self._provider_breaker(config).call(
                self._embeddings.embed,
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
                    # A Decimal, not `0.0`: `model_calls.cost` is
                    # `AI_COST = Numeric(18,8)`, so this is a money column, and
                    # the chat path beside it (`_record_run`) already writes
                    # `Decimal(0)`. Two spellings of "zero cost" in one module is
                    # how a float sneaks back into the ledger.
                    cost=Decimal(0),
                    latency_ms=latency_ms,
                    status=status,
                )
            )
            await session.flush()
