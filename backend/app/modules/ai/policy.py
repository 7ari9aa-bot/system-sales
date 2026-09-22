"""Spec §43 — AI provider data governance: which providers/models may receive data.

This is a **DATA-EGRESS decision, not an authorization decision**. Authorization
asks "may this user/tenant perform the action?" (see ``require_permission`` and
``EntitlementService``). This service asks a different question: *given that the
action is already authorized, is this tenant allowed to send THIS classified
payload to THIS provider/model at all?* A caller must apply both.

Everything here is expressed by the ``AIProviderPolicy`` model and nothing more:
one row per ``(tenant_id, provider)`` (unique constraint), carrying

- ``status``               — ``allowed`` | ``denied`` (the provider switch),
- ``allowed_models``       — a JSONB allow-list; empty means "any model",
- ``pii_redaction_required`` — the provider may only be used after PII redaction,
- ``data_classification``  — the most sensitive class this provider is cleared for,
- ``notes``                — free text for humans.

Precedence (highest first), documented because it is the whole point:

1. An **explicit deny** (``status == "denied"``) wins over everything — including
   a model that appears in ``allowed_models``. Deny always beats allow.
2. A non-empty ``allowed_models`` allow-list: a model not listed is denied.
3. Classification clearance: data classified above the provider's
   ``data_classification`` is denied (see ``_CLASSIFICATION_ORDER``).
4. Otherwise the call is allowed, and ``redact_required`` mirrors the policy's
   ``pii_redaction_required`` flag.

**Fail-open is the documented house default** for capabilities (see
``EntitlementService.can``: "unknown capabilities are allowed by default").
The same applies here: a provider with **no** policy row is allowed, because
shipping enforcement must not silently cut off every tenant that has not been
given a policy yet. Turning a provider off is an explicit, auditable act.

The service never commits — it flushes inside the caller's transaction.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationError
from app.modules.ai.models import AIProviderPolicy

# Ordered data-classification ladder. A provider policy declares the most
# sensitive class it is cleared to receive; anything above it is denied.
# Unknown tokens are deliberately *unranked*: they cannot be compared, so the
# classification check is skipped rather than guessed (fail-open, per house
# default) — an operator who wants strictness uses one of these values.
_CLASSIFICATION_ORDER: dict[str, int] = {
    "public": 0,
    "internal": 1,
    "confidential": 2,
    "restricted": 3,
}

POLICY_STATUSES = frozenset({"allowed", "denied"})

# §43 "Classify" — the payload decides its own class. A prompt that carries
# direct identifiers is ``restricted``; anything else is treated as ordinary
# tenant business data (``internal``). Deliberately coarse: this is an egress
# gate, not a DLP product, and the ladder in _CLASSIFICATION_ORDER only has
# these two practical rungs in our flows.
_RESTRICTED_RE = re.compile(
    r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"  # email
    r"|\+?\d[\d\s\-()]{7,}\d"  # phone (intl-ish, separators allowed)
    r"|\b(?:\d[ -]*?){13,19}\b"  # card number
    r"|\b[1-2]\d{13}\b"  # national ID (14-digit, Egypt-style)
)


def classify_data(payload) -> str:
    """Classify what is about to leave the tenant boundary (§43).

    Accepts the provider message list (``[{"role", "content"}]``), a list of
    plain strings (the embedding path), or a single string. Tool-call
    arguments are server-side bound and already tenant-scoped (§132), so only
    text content is scanned.
    """
    if isinstance(payload, str):
        texts = [payload]
    elif isinstance(payload, list):
        texts = []
        for item in payload:
            if isinstance(item, str):
                texts.append(item)
            elif isinstance(item, dict) and isinstance(item.get("content"), str):
                texts.append(item["content"])
    else:  # pragma: no cover - defensive
        return "internal"
    joined = "\n".join(texts)
    return "restricted" if _RESTRICTED_RE.search(joined) else "internal"


def _region_matches(residency: str, region: str) -> bool:
    """Does a provider region satisfy the declared residency?

    Substring match both ways so "eu" matches "eu-west-1" and "Frankfurt
    (eu-central-1)" — residency tokens are operator-declared, provider
    regions are configuration strings; a strict equality check would deny on
    formatting noise and teach nobody anything.
    """
    r = residency.strip().lower()
    g = region.strip().lower()
    return bool(r) and bool(g) and (r in g or g in r)


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    """Outcome of a §43 data-egress evaluation.

    ``policy_id`` is None when no policy row applied (the fail-open case), so a
    caller can tell "allowed because a policy said so" apart from "allowed
    because there is no policy".
    """

    allowed: bool
    reason: str
    redact_required: bool
    policy_id: uuid.UUID | None


def _level(value: str | None) -> int | None:
    """Rank a classification token, or None when it is not on the ladder."""
    if not value:
        return None
    return _CLASSIFICATION_ORDER.get(value.strip().lower())


def decide(
    policy: AIProviderPolicy | None,
    *,
    provider: str,
    model: str | None,
    data_class: str | None,
    region: str | None = None,
) -> PolicyDecision:
    """Pure precedence function — no session, so it is directly testable.

    ``AIProviderPolicyService.evaluate`` loads the row and delegates here. Kept
    module-level (not a method) precisely so the precedence rules can be pinned
    without a database. ``region`` is where the resolved model actually runs
    (from the model config's ``region`` key); it is only consulted when the
    policy declares a residency.
    """
    if policy is None:
        # Fail-open: no policy for this provider ⇒ allowed. See module docstring.
        return PolicyDecision(
            allowed=True,
            reason=f"no policy for provider '{provider}'; allowed by default (fail-open)",
            redact_required=False,
            policy_id=None,
        )

    # 1. Explicit deny beats any allow, including a listed model.
    if policy.status == "denied":
        return PolicyDecision(
            allowed=False,
            reason=f"provider '{provider}' is explicitly denied by policy",
            redact_required=False,
            policy_id=policy.id,
        )

    # 2. Model allow-list. Empty list ⇒ any model permitted.
    allowed_models = list(policy.allowed_models or [])
    if allowed_models and model is not None and model not in allowed_models:
        return PolicyDecision(
            allowed=False,
            reason=(
                f"model '{model}' is not in provider '{provider}' allowed_models "
                f"{sorted(allowed_models)}"
            ),
            redact_required=False,
            policy_id=policy.id,
        )

    # 3. §43 Data residency: a declared residency is a hard constraint, and
    # an unknown provider region fails CLOSED — "we don't know where this
    # runs" is not the same as "it runs inside the residency you declared".
    residency = (getattr(policy, "data_residency", None) or "").strip()
    if residency:
        if not (region or "").strip():
            return PolicyDecision(
                allowed=False,
                reason=(
                    f"data residency '{residency}' declared but provider '{provider}' "
                    "region is unknown — configure the model config's 'region'"
                ),
                redact_required=False,
                policy_id=policy.id,
            )
        if not _region_matches(residency, region or ""):
            return PolicyDecision(
                allowed=False,
                reason=(
                    f"data residency '{residency}' violated: provider '{provider}' "
                    f"runs in region '{region}'"
                ),
                redact_required=False,
                policy_id=policy.id,
            )

    # 4. Classification clearance. Only enforced when both sides are ranked.
    data_level = _level(data_class)
    cleared_level = _level(policy.data_classification)
    if data_level is not None and cleared_level is not None and data_level > cleared_level:
        return PolicyDecision(
            allowed=False,
            reason=(
                f"data class '{data_class}' exceeds provider '{provider}' clearance "
                f"'{policy.data_classification}'"
            ),
            redact_required=False,
            policy_id=policy.id,
        )

    # 5. Allowed by policy; redaction is whatever the policy demands.
    return PolicyDecision(
        allowed=True,
        reason=f"provider '{provider}' allowed by policy",
        redact_required=bool(policy.pii_redaction_required),
        policy_id=policy.id,
    )


class AIProviderPolicyService:
    """Read/decide/write the tenant's §43 provider policies."""

    @staticmethod
    async def evaluate(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        provider: str,
        model: str | None = None,
        data_class: str | None = None,
        region: str | None = None,
    ) -> PolicyDecision:
        """Decide whether ``data_class``-classified data may go to ``provider``.

        **Absent policy ⇒ allowed** (fail-open; see module docstring). An
        explicit deny always wins over any allow. This is a data-egress
        decision, NOT an authorization decision: it does not check user
        permissions, entitlements or budgets. ``region`` is consulted only
        when the policy declares a data residency.
        """
        policy = (
            await session.execute(
                select(AIProviderPolicy).where(
                    AIProviderPolicy.tenant_id == tenant_id,
                    AIProviderPolicy.provider == provider,
                )
            )
        ).scalar_one_or_none()
        return decide(
            policy, provider=provider, model=model, data_class=data_class, region=region
        )

    @staticmethod
    async def list_policies(
        session: AsyncSession, tenant_id: uuid.UUID
    ) -> list[AIProviderPolicy]:
        """Every provider policy for the tenant, provider-name ordered."""
        rows = (
            await session.execute(
                select(AIProviderPolicy)
                .where(AIProviderPolicy.tenant_id == tenant_id)
                .order_by(AIProviderPolicy.provider.asc())
            )
        ).scalars()
        return list(rows.all())

    @staticmethod
    async def upsert(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        provider: str,
        status: str = "allowed",
        allowed_models: list[str] | None = None,
        pii_redaction_required: bool = False,
        data_classification: str = "internal",
        notes: str | None = None,
        data_residency: str | None = None,
        retention_terms: str | None = None,
    ) -> AIProviderPolicy:
        """Create or replace the ``(tenant_id, provider)`` policy row."""
        if status not in POLICY_STATUSES:
            raise ValidationError(
                f"invalid policy status: {status}",
                details={"allowed": sorted(POLICY_STATUSES)},
            )
        if not provider:
            raise ValidationError("provider is required")

        policy = (
            await session.execute(
                select(AIProviderPolicy).where(
                    AIProviderPolicy.tenant_id == tenant_id,
                    AIProviderPolicy.provider == provider,
                )
            )
        ).scalar_one_or_none()
        if policy is None:
            policy = AIProviderPolicy(tenant_id=tenant_id, provider=provider)
            session.add(policy)

        policy.status = status
        policy.allowed_models = list(allowed_models or [])
        policy.pii_redaction_required = pii_redaction_required
        policy.data_classification = data_classification
        policy.data_residency = (data_residency or "").strip() or None
        policy.retention_terms = (retention_terms or "").strip() or None
        policy.notes = notes
        await session.flush()
        return policy
