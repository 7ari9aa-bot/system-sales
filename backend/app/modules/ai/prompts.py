"""AI Prompts — default and fallback system prompts.

Centralises system prompt templates and emergency fallbacks for the runtime.
"""

from __future__ import annotations

from app.modules.ai.agents.customer.prompts import CUSTOMER_SYSTEM_PROMPT

# Canonical default prompt for customer-facing agent runtime
DEFAULT_SYSTEM_PROMPT: str = CUSTOMER_SYSTEM_PROMPT

#: Polite holding message sent while an awaiting-approval run is pending, so
#: the customer does not get complete silence (§135/P1-9, runtime.py).
AWAITING_APPROVAL_MESSAGE: str = (
    "تم تحويل طلبك لفريق العمل للمراجعة والموافقة وسنوافيك بالرد فور اعتماده."
)
