"""Outbound marketing-consent gate (spec §32).

Consent is NOT a boolean: it is scoped by (customer, channel, purpose) and kept
as an append-only ledger (``app.modules.privacy.models.Consent``). This module
answers one question for a promotional send — *may we send this to this customer
on this channel?*

It is called from ``ConversationService.add_promotional_message``, the ONE door
that can produce a ``purpose="marketing"`` message. There is deliberately no
``purpose`` argument anywhere on the generic outbound path: a caller cannot
forget to declare marketing, because marketing is the only thing the door sends.

Why ``app/core`` and not ``app.modules.privacy``: ``privacy`` imports
``customers``, and ``customers`` <-> ``conversations`` is already an import
cycle, so a ``conversations -> privacy`` import closes a NEW cycle
(``conversations -> customers -> privacy``). The boundary ratchet in
``tests/test_module_boundaries.py`` counts function-scope imports too, so a lazy
import does not help — ``app.core.guardrails`` lives here for the same reason.

The ledger is read with SQL rather than the ORM model so that ``app/core`` stays
free of domain-module imports (the same rule that keeps ``guardrails.py``
model-free); ``app/core/db.py`` and ``app/core/lease.py`` already query with
``text()``.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationError

# The purpose a promotional send is recorded and gated under.
MARKETING_PURPOSE = "marketing"

# The purposes the Consent ledger records (see privacy/router.py ConsentGrant).
CONSENT_PURPOSES = frozenset(
    {"service_messages", MARKETING_PURPOSE, "ai_processing", "analytics"}
)

# Purposes that may NOT reach a customer without a currently-granted consent.
#
# Only "marketing". A service message is the customer's own order/support
# conversation, and refusing a shipping notification for lack of *marketing*
# consent would be a serious regression; ai_processing/analytics are processing
# consents, not send-time gates.
CONSENT_REQUIRED_PURPOSES = frozenset({MARKETING_PURPOSE})


def purpose_requires_consent(purpose: str) -> bool:
    """True when this purpose may not be sent without a granted consent."""
    return purpose in CONSENT_REQUIRED_PURPOSES


def validate_purpose(purpose: str) -> str:
    """Reject a purpose the Consent ledger cannot record."""
    normalized = purpose.strip().lower()
    if normalized not in CONSENT_PURPOSES:
        raise ValidationError(
            f"unknown message purpose {purpose!r}; expected one of "
            f"{sorted(CONSENT_PURPOSES)}"
        )
    return normalized


@dataclass(frozen=True, slots=True)
class ConsentDecision:
    """The verdict, plus everything the caller needs to explain it."""

    allowed: bool
    reason: str
    purpose: str
    channel: str
    required: bool


# The latest decision for (tenant, customer, channel, purpose) wins: a grant that
# was later revoked, or a revocation followed by a re-grant, both resolve to
# whichever happened last. `revoked_at` is set in place by the revoke endpoint,
# so the decision instant is GREATEST(captured_at, revoked_at).
_LATEST_CONSENT_STATUS = text(
    """
    SELECT status
      FROM consents
     WHERE tenant_id = :tenant_id
       AND customer_id = :customer_id
       AND channel = :channel
       AND purpose = :purpose
     ORDER BY GREATEST(captured_at, COALESCE(revoked_at, captured_at)) DESC
     LIMIT 1
    """
)


async def evaluate_outbound_consent(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    customer_id: uuid.UUID,
    channel: str,
    purpose: str,
) -> ConsentDecision:
    """Decide whether consent permits sending on this channel for this purpose.

    Tenant-scoped: the lookup always filters ``tenant_id``, so a grant recorded
    for one tenant can never authorise a send for another.
    """
    resolved = validate_purpose(purpose)
    if not purpose_requires_consent(resolved):
        return ConsentDecision(
            allowed=True,
            reason=f"purpose {resolved!r} does not require consent",
            purpose=resolved,
            channel=channel,
            required=False,
        )

    status = (
        await session.execute(
            _LATEST_CONSENT_STATUS,
            {
                "tenant_id": tenant_id,
                "customer_id": customer_id,
                "channel": channel,
                "purpose": resolved,
            },
        )
    ).scalar_one_or_none()

    if status == "granted":
        return ConsentDecision(
            allowed=True,
            reason=f"{resolved} consent granted for channel {channel!r}",
            purpose=resolved,
            channel=channel,
            required=True,
        )
    return ConsentDecision(
        allowed=False,
        reason=(
            f"no granted {resolved} consent for channel {channel!r} "
            f"(consent state: {status or 'no consent on record'})"
        ),
        purpose=resolved,
        channel=channel,
        required=True,
    )


__all__ = [
    "CONSENT_PURPOSES",
    "CONSENT_REQUIRED_PURPOSES",
    "MARKETING_PURPOSE",
    "ConsentDecision",
    "evaluate_outbound_consent",
    "purpose_requires_consent",
    "validate_purpose",
]
