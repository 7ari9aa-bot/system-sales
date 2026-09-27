"""AI output guardrails — moved to app/core/guardrails.py (spec §41/§173).

Kept as a re-export so existing importers (`ai/runtime.py`, `tests/gate`) do not
break, and so the AI module keeps a stable address for its own guardrail.

It moved because §173 requires the check at the boundary that actually inserts an
outbound message (`conversations.service.add_message`), and `ai` already imports
`conversations` — so `conversations` importing `ai.guardrails` would close an
import cycle, which tests/test_module_boundaries.py fails on. The chain is pure,
so it belongs in core where both modules may depend on it.

Import from `app.core.guardrails` in new code.
"""

from __future__ import annotations

from app.core.guardrails import (
    AI_SENDER_TYPES,
    GuardrailVerdict,
    OutputGuardrail,
    claim_checks,
    claims_facts,
    default_guardrail,
    screen_inbound,
)

__all__ = [
    "AI_SENDER_TYPES",
    "GuardrailVerdict",
    "OutputGuardrail",
    "claim_checks",
    "claims_facts",
    "default_guardrail",
    "screen_inbound",
]
