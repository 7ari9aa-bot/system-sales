"""AI output guardrails (spec §41/§173).

Chain order before ANY outbound AI content:
    schema/validity → policy checks → factual constraints (tool results)
    → PII leakage → brand/tone → channel policy → approval gate

A guardrail verdict is either ALLOW or BLOCK(+reason) or HANDOVER. Tool
authorization answers "may the AI act?"; guardrails answer "may this text be
sent?" — both are required.

Lives in `app/core` rather than `app/modules/ai` because §173 requires the
check to be enforced at the boundary that actually inserts an outbound message
(`conversations.service.add_message`), not only inside the AI runner. `ai`
already imports `conversations`, so a `conversations -> ai` import would close
an import cycle. The chain is pure (regex + dataclasses, no models, no session),
so it belongs in core anyway — both modules may depend on it.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field

# Patterns that must never leak from internal context into customer messages.
_PII_PATTERNS = [
    (re.compile(r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b"), "card_number"),
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "ssn_like"),
    (re.compile(r"sk-[A-Za-z0-9]{20,}"), "api_key"),
    (re.compile(r"(?i)internal_cost|supplier_price|margin"), "internal_margin"),
]

_INJECTION_MARKERS = [
    "ignore previous instructions",
    "system prompt:",
    "disregard all rules",
    "تجاهل التعليمات",
]


@dataclass
class GuardrailVerdict:
    decision: str  # allow | block | handover
    reason: str | None = None
    checks: list[str] = field(default_factory=list)


class OutputGuardrail:
    """Configurable chain. Each check returns None (pass) or a verdict."""

    def __init__(self) -> None:
        self._checks: list[tuple[str, Callable[[str, dict], GuardrailVerdict | None]]] = []

    def add_check(
        self, name: str, fn: Callable[[str, dict], GuardrailVerdict | None]
    ) -> OutputGuardrail:
        self._checks.append((name, fn))
        return self

    def evaluate(self, content: str, context: dict) -> GuardrailVerdict:
        checks_run: list[str] = []
        for name, fn in self._checks:
            checks_run.append(name)
            verdict = fn(content, context)
            if verdict is not None and verdict.decision != "allow":
                verdict.checks = checks_run
                return verdict
        return GuardrailVerdict(decision="allow", checks=checks_run)


def default_guardrail(*, require_tool_evidence: bool = False) -> OutputGuardrail:
    """Production-default chain.

    `require_tool_evidence` is off by default because it needs the run's tool
    results, which only the AI runner has. The content-only checks (validity,
    PII, injection) apply everywhere, including the outbound-message boundary.
    """
    chain = OutputGuardrail()

    def _validity(content: str, ctx: dict) -> GuardrailVerdict | None:
        if not content or not content.strip():
            return GuardrailVerdict(decision="block", reason="empty content")
        return None

    def _pii(content: str, ctx: dict) -> GuardrailVerdict | None:
        for pattern, label in _PII_PATTERNS:
            if pattern.search(content):
                return GuardrailVerdict(
                    decision="block", reason=f"pii_leak:{label}"
                )
        return None

    def _injection_echo(content: str, ctx: dict) -> GuardrailVerdict | None:
        low = content.lower()
        if any(marker in low for marker in _INJECTION_MARKERS):
            return GuardrailVerdict(decision="handover", reason="injection_risk")
        return None

    def _tool_evidence(content: str, ctx: dict) -> GuardrailVerdict | None:
        # Factual constraint: price/stock claims must come from tool results.
        if require_tool_evidence and ctx.get("claims_facts") and not ctx.get("tool_results"):
            return GuardrailVerdict(decision="handover", reason="unsourced_claim")
        return None

    chain.add_check("validity", _validity)
    chain.add_check("pii", _pii)
    chain.add_check("injection_echo", _injection_echo)
    chain.add_check("tool_evidence", _tool_evidence)
    return chain


# The sender types whose content is AI-authored and must pass the chain. A human
# agent's own words are their responsibility; a `system` notice is not customer
# prose.
AI_SENDER_TYPES: frozenset[str] = frozenset({"ai"})
