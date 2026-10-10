"""Server-side customer confirmation for orders (P1-10).

The model proposes an order; the SERVER mints a quote row plus an expiring
6-digit code that the reply echoes into the chat. Only the CUSTOMER's own
next message — matched server-side for the code — turns the quote into a
confirmed one, and only a confirmed quote authorizes ``create_order`` to
execute, with the QUOTE's items. The model can read the code (it must show
it) but can never confirm on the customer's behalf: confirmation is a state
transition keyed to an inbound message, never to a tool argument or a model
sentence. One live quote per conversation at a time — a second proposal
while one is live would orphan the code the customer is about to type.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ai.models import AIOrderQuote

#: How long the customer has to type the code back.
QUOTE_TTL_MINUTES = 15

_CODE_DIGITS = 6


def _now() -> datetime:
    return datetime.now(UTC)


def _new_code() -> str:
    return f"{secrets.randbelow(10**_CODE_DIGITS):06d}"


async def expire_stale_quotes(session: AsyncSession, tenant_id: uuid.UUID) -> int:
    """Quotes past their expiry are dead for both phases.

    A PENDING quote past expiry can no longer be confirmed; a CONFIRMED one
    can no longer be executed (the tool refuses it), and leaving it live
    would block the conversation from ever minting a fresh quote — one live
    quote per conversation is the rule that keeps codes un-orphaned.
    """
    result = await session.execute(
        update(AIOrderQuote)
        .where(
            AIOrderQuote.tenant_id == tenant_id,
            AIOrderQuote.status.in_(("pending", "confirmed")),
            AIOrderQuote.expires_at <= _now(),
        )
        .values(status="expired")
    )
    return result.rowcount or 0


async def mint_quote(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    conversation_id: uuid.UUID,
    customer_id: uuid.UUID,
    items: list[dict],
    grand_total: Decimal,
    currency: str = "EGP",
) -> AIOrderQuote:
    quote = AIOrderQuote(
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        customer_id=customer_id,
        items=items,
        grand_total=grand_total,
        currency=currency,
        code=_new_code(),
        expires_at=_now() + timedelta(minutes=QUOTE_TTL_MINUTES),
    )
    session.add(quote)
    await session.flush()
    return quote


async def live_quote(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    conversation_id: uuid.UUID,
    customer_id: uuid.UUID,
) -> AIOrderQuote | None:
    """The conversation's live quote: pending (awaiting the code) or confirmed
    but not yet consumed (awaiting execution). Expiry is applied first, so a
    stale pending quote is never served."""
    await expire_stale_quotes(session, tenant_id)
    return (
        (
            await session.execute(
                select(AIOrderQuote)
                .where(
                    AIOrderQuote.tenant_id == tenant_id,
                    AIOrderQuote.conversation_id == conversation_id,
                    AIOrderQuote.customer_id == customer_id,
                    AIOrderQuote.status.in_(("pending", "confirmed")),
                )
                .order_by(AIOrderQuote.created_at.desc())
                .limit(1)
            )
        )
        .scalars()
        .first()
    )


async def match_confirmation(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    conversation_id: uuid.UUID,
    customer_id: uuid.UUID,
    text: str | None,
) -> AIOrderQuote | None:
    """The customer's code, matched server-side.

    A pending quote becomes confirmed only when the CUSTOMER's message carries
    the code. A quote that is already confirmed-but-unconsumed stays confirmed
    (the customer did confirm once — an approval-resume or a follow-up turn
    must still be able to execute it until it is consumed or expires). Anything
    else returns None.

    The customer's message is matched in plain text: the code is shown to them
    in chat and they type it back; anything else the model claims about
    confirmation is irrelevant to this transition.
    """
    quote = await live_quote(
        session, tenant_id, conversation_id=conversation_id, customer_id=customer_id
    )
    if quote is None:
        return None
    if quote.status == "pending":
        if not text or quote.code not in text:
            return None
        quote.status = "confirmed"
        quote.confirmed_at = _now()
        # Confirmation starts the EXECUTION window: the order still waits on
        # §135 merchant approval, which can take longer than the customer's
        # reply. Without a refreshed expiry a slow approval would strand a
        # quote the customer confirmed on time.
        quote.expires_at = _now() + timedelta(minutes=QUOTE_TTL_MINUTES)
        await session.flush()
    return quote


def quote_payload(quote: AIOrderQuote) -> dict:
    """What the tool returns to the model: the proposal, the code, the rule."""
    return {
        "quote_id": str(quote.id),
        "items": quote.items,
        "grand_total": str(quote.grand_total),
        "currency": quote.currency,
        "confirmation_code": quote.code,
        "expires_at": quote.expires_at.isoformat(),
        "status": quote.status,
        "instruction": (
            "الطلب لم ينفذ بعد — اعرض الملخص على العميل واطلب منه تأكيد الطلب "
            "بكتابة كود التأكيد. لا تنفذ الطلب قبل أن يرسل العميل الكود بنفسه."
        ),
    }
