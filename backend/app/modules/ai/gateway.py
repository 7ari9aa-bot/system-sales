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
from decimal import Decimal
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import errors as _errors
from app.core.circuit_breaker import PROVIDER_AI, get_breaker
from app.core.config import get_settings
from app.core.errors import ValidationError
from app.modules.ai import budget as _budget
from app.modules.ai.models import ModelCall, ModelConfig
from app.modules.ai.providers import (
    AIProvider,
    ChatCompletionResult,
    EmbeddingProvider,
    JinaMultimodalEmbeddingProvider,
    MultimodalContent,
    MultimodalEmbeddingProvider,
    RerankerProvider,
)

# Budget management & financial guardrails (Section 42): the implementation
# lives in budget.py; the gateway is the surface runtime, the message worker
# and the test suite import these names FROM. Plain assignments, not aliased
# imports: a lint sweep that read aliased re-exports as dead imports crashed
# the workers service at import time (2026-10-17) - assignments survive it.
BUDGET_ALERT_THRESHOLDS = _budget.BUDGET_ALERT_THRESHOLDS
BUDGET_LOCK_WAIT_SECONDS = _budget.BUDGET_LOCK_WAIT_SECONDS
MONTHLY_BUDGET_CAP = _budget.MONTHLY_BUDGET_CAP
RESERVATION_TTL_MINUTES = _budget.RESERVATION_TTL_MINUTES
_COST_PER_INPUT_TOKEN = _budget._COST_PER_INPUT_TOKEN
_COST_PER_OUTPUT_TOKEN = _budget._COST_PER_OUTPUT_TOKEN
_IMAGE_TOKEN_FLOOR = _budget._IMAGE_TOKEN_FLOOR
_daily_cap = _budget._daily_cap
_day_spend = _budget._day_spend
_default_cap = _budget._default_cap
_month_spend = _budget._month_spend
_on_budget_exceeded = _budget._on_budget_exceeded
_raise_budget_alerts = _budget._raise_budget_alerts
_reserved_spend = _budget._reserved_spend
_resolve_cap = _budget._resolve_cap
_tenant_budget_lock_id = _budget._tenant_budget_lock_id
AIBudgetExhaustedError = _budget.AIBudgetExhaustedError
AIBudgetFallbackRequested = _budget.AIBudgetFallbackRequested
RateLimitExceededError = _errors.RateLimitExceededError
enforce_budget = _budget.enforce_budget
estimate_cost = _budget.estimate_cost
expire_stale_reservations = _budget.expire_stale_reservations
reserve_budget = _budget.reserve_budget
settle_reservation = _budget.settle_reservation

logger = logging.getLogger(__name__)

ALIASES = frozenset({"fast", "strong", "cheap", "embedding", "fallback", "omni"})


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


def _contains_nontext_media(messages: list[dict]) -> bool:
    """Whether a provider payload contains image/audio/video bytes or URLs."""
    for message in messages:
        content = message.get("content")
        if not isinstance(content, list):
            continue
        if any(
            isinstance(part, dict)
            and part.get("type") in {"image_url", "input_audio", "audio_url", "video_url"}
            for part in content
        ):
            return True
    return False


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
        elif role in ("user", "assistant", "system") and isinstance(content, list):
            parts = []
            for part in content:
                if (
                    isinstance(part, dict)
                    and part.get("type") == "text"
                    and isinstance(part.get("text"), str)
                ):
                    text = part["text"]
                    for pattern, replacement in _PII_PATTERNS:
                        text = pattern.sub(replacement, text)
                    parts.append({**part, "text": text})
                else:
                    parts.append(part)
            redacted.append({**msg, "content": parts})
        else:
            redacted.append(msg)
    return redacted


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
        api_key = str(config.get("api_key") or "")
        # §68: secret_ref overrides the inlined api_key when present.
        if row.secret_ref:
            from app.core.secrets import get_secret_store
            from app.core.tenancy import tenant_scope

            # The secret store resolves its scope from the CONTEXT variable,
            # not this session — an HTTP request binds it in identity/deps,
            # but a worker (or any future caller) may reach here without it.
            # The tenant_id is a parameter of THIS function: bind it for the
            # lookup instead of failing closed one layer away from the bug.
            async with tenant_scope(session, tenant_id):
                secret_value = await get_secret_store().get_or_none(row.secret_ref)
            if secret_value:
                api_key = secret_value
        return {
            "provider": row.provider,
            "model": row.model,
            "base_url": str(config.get("base_url") or ""),
            "api_key": api_key,
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


# Budget management functions & guardrails (§42) are implemented in
# app.modules.ai.budget and re-exported above for backward compatibility.


class AIGateway:
    """Single entry point for model calls — resolves config, records spend."""

    def __init__(self, provider: AIProvider | None = None) -> None:
        self._provider = provider or AIProvider()
        self._embeddings = EmbeddingProvider()
        self._vision_embeddings = MultimodalEmbeddingProvider()
        self._vision_embeddings_jina = JinaMultimodalEmbeddingProvider()
        self._reranker = RerankerProvider()

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
                if _contains_nontext_media(messages):
                    # Text redaction cannot remove spoken PII, labels embedded
                    # in a photo, or the media itself. Do not send any
                    # multimodal payload under a policy that requires
                    # redaction we cannot faithfully perform.
                    raise ValidationError(
                        "AI provider policy requires redaction, but this request contains "
                        "non-text media that cannot be redacted"
                    )
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
        # §42: embeddings spend budget like chat — reserve up front so the cap
        # holds under concurrency, then settle after the call.
        estimated_tokens = sum(len(t) for t in texts) // 4
        estimated = estimate_cost(tokens_in=estimated_tokens, tokens_out=0)
        reservation_id = await reserve_budget(
            session, tenant_id, agent_id=None, estimated_cost=estimated
        )
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
                    tokens_in=estimated_tokens,
                    tokens_out=0,
                    cost=estimated,
                    latency_ms=latency_ms,
                    status=status,
                )
            )
            # §42 settle: release the hold whether the call succeeded or not.
            try:
                await asyncio.shield(settle_reservation(session, reservation_id))
                await asyncio.shield(session.flush())
            except Exception:
                logger.warning(
                    "ai.settle_reservation_failed reservation=%s",
                    reservation_id,
                    exc_info=True,
                )

    async def embed_vision(
        self,
        session: AsyncSession,
        tenant_id: UUID,
        *,
        contents: list[MultimodalContent],
        run_id: UUID | None = None,
        _client: Any | None = None,
    ) -> list[list[float]]:
        """Embed image/text contents through the vision embedding provider.

        Same governance skeleton as embed() — budget reservation, data-egress
        policy, endpoint breaker, ModelCall row. The vision modules used to
        call MultimodalEmbeddingProvider directly: real provider spend with no
        reservation and no record, so a tenant over its cap could still burn
        money by sending photos.

        Captions can be redacted; an image URL cannot (redacting one destroys
        the request), so redaction applies to text parts only. The image
        token floor is a billing abstraction — the provider bills per image,
        the exact number is opaque, and the budget cap needs a positive
        estimate to enforce anything at all.
        """
        settings = get_settings()
        if not contents:
            raise ValueError("contents must not be empty")
        provider = settings.ai_embedding_vision_provider
        model = settings.ai_embedding_vision_model
        base_url = settings.ai_embedding_vision_base_url
        api_key = settings.ai_embedding_vision_api_key
        if not base_url or not api_key:
            raise ValidationError("vision embedding provider is not configured")

        estimated_tokens = sum(
            (len(c.text) // 4 if c.text else 0) + (_IMAGE_TOKEN_FLOOR if c.image else 0)
            for c in contents
        )
        estimated = estimate_cost(tokens_in=estimated_tokens, tokens_out=0)
        reservation_id = await reserve_budget(
            session, tenant_id, agent_id=None, estimated_cost=estimated
        )

        from app.modules.ai.policy import AIProviderPolicyService, classify_data

        started = time.perf_counter()
        status = "ok"
        vectors: list[list[float]] = []
        try:

            def _classify() -> str:
                return classify_data(
                    [
                        {
                            "role": "user",
                            "content": c.text if c.text is not None else c.image,
                        }
                        for c in contents
                    ]
                )

            decision = await AIProviderPolicyService.evaluate(
                session,
                tenant_id,
                provider=provider,
                model=model,
                data_class=_classify(),
                region=None,
            )
            if decision.redact_required:
                contents = [
                    MultimodalContent(
                        text=(
                            _redact_pii([{"role": "user", "content": c.text}])[0]["content"]
                            if c.text is not None
                            else None
                        ),
                        image=c.image,
                    )
                    for c in contents
                ]
                decision = await AIProviderPolicyService.evaluate(
                    session,
                    tenant_id,
                    provider=provider,
                    model=model,
                    data_class=_classify(),
                    region=None,
                )
            if not decision.allowed:
                raise ValidationError(
                    f"AI vision provider blocked by data-egress policy: {decision.reason}"
                )

            embedder = (
                self._vision_embeddings_jina if provider == "jina" else self._vision_embeddings
            )
            vectors = await self._provider_breaker({"base_url": base_url}).call(
                embedder.embed,
                base_url=base_url,
                api_key=api_key,
                model=model,
                contents=contents,
                expected_dimensions=settings.ai_embedding_vision_dimensions,
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
                    alias="vision_embedding",
                    provider=provider,
                    model=model,
                    tokens_in=estimated_tokens,
                    tokens_out=0,
                    cost=estimated,
                    latency_ms=latency_ms,
                    status=status,
                )
            )
            try:
                await asyncio.shield(settle_reservation(session, reservation_id))
                await asyncio.shield(session.flush())
            except Exception:
                logger.warning(
                    "ai.settle_reservation_failed reservation=%s",
                    reservation_id,
                    exc_info=True,
                )

    async def rerank_vision(
        self,
        session: AsyncSession,
        tenant_id: UUID,
        *,
        query: str,
        documents: list[dict[str, str]],
        top_n: int | None = None,
        run_id: UUID | None = None,
        _client: Any | None = None,
    ) -> list:
        """Rerank through the reranker provider under the same governance.

        The payload is image URLs plus the query URL — nothing redactable, so
        a policy that demands redaction blocks the call instead of sending
        unredacted data.
        """
        settings = get_settings()
        provider = settings.ai_reranker_provider
        model = settings.ai_reranker_model
        base_url = settings.ai_reranker_base_url
        api_key = settings.ai_reranker_api_key
        if not base_url or not api_key:
            raise ValidationError("reranker provider is not configured")

        estimated_tokens = (len(query) // 4) + _IMAGE_TOKEN_FLOOR * len(documents)
        estimated = estimate_cost(tokens_in=estimated_tokens, tokens_out=0)
        reservation_id = await reserve_budget(
            session, tenant_id, agent_id=None, estimated_cost=estimated
        )

        from app.modules.ai.policy import AIProviderPolicyService, classify_data

        started = time.perf_counter()
        status = "ok"
        results: list = []
        try:
            data_class = classify_data(
                [{"role": "user", "content": query}]
                + [{"role": "user", "content": d.get("image", "")} for d in documents]
            )
            decision = await AIProviderPolicyService.evaluate(
                session,
                tenant_id,
                provider=provider,
                model=model,
                data_class=data_class,
                region=None,
            )
            if not decision.allowed or decision.redact_required:
                raise ValidationError(
                    f"AI reranker blocked by data-egress policy: {decision.reason}"
                )

            results = await self._provider_breaker({"base_url": base_url}).call(
                self._reranker.rerank,
                base_url=base_url,
                api_key=api_key,
                model=model,
                query=query,
                documents=documents,
                top_n=top_n,
                _client=_client,
            )
            return results
        except Exception:
            status = "error"
            raise
        finally:
            latency_ms = int((time.perf_counter() - started) * 1000)
            session.add(
                ModelCall(
                    tenant_id=tenant_id,
                    run_id=run_id,
                    alias="vision_rerank",
                    provider=provider,
                    model=model,
                    tokens_in=estimated_tokens,
                    tokens_out=0,
                    cost=estimated,
                    latency_ms=latency_ms,
                    status=status,
                )
            )
            try:
                await asyncio.shield(settle_reservation(session, reservation_id))
                await asyncio.shield(session.flush())
            except Exception:
                logger.warning(
                    "ai.settle_reservation_failed reservation=%s",
                    reservation_id,
                    exc_info=True,
                )
