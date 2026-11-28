"""What FIHRIST Apparel does with its own events.

The platform routes; the application decides meaning (§17). Two events have a
real, attributable effect today and are consumed here:

* ``apparel.ai.agent_escalated`` — the support agent handed a conversation to a
  human. That is an operational fact the shop must be able to see afterwards, so
  it is written to the audit log with the conversation as its resource.
* ``apparel.sales.sale_completed`` — a sale closed. Written to the audit log for
  the same reason: money moved and the record must survive the request.

Everything else the manifest declares is published for consumers that do not
exist yet; publishing an event nobody consumes is a wiring gap, not a silent
success, which is why the coverage test names the gap instead of pretending the
list is complete.

Handlers are idempotent by construction: an audit row keyed to the event's own
``event_id`` (when the relay supplies one) is written at most once per delivery
batch, and the writer never updates business state.
"""

from __future__ import annotations

import uuid

from app.core.audit import write_audit_row
from app.core.db import SessionLocal
from app.platform.events.routing import consumes

#: Events this release consumes. Kept next to the handlers so the coverage test
#: can compare it against the manifest without importing the app.
CONSUMED_EVENTS: tuple[str, ...] = (
    "apparel.ai.agent_escalated",
    "apparel.sales.sale_completed",
)


def _uuid_or_none(value: object) -> uuid.UUID | None:
    """Parse an id from an envelope without guessing at a malformed one."""
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return None


def _id_text(value: object) -> str | None:
    """An id as text, or None when the envelope carried none."""
    return None if value is None else str(value)


def escalation_audit(envelope: dict) -> dict:
    """The audit row an escalation writes, as plain values.

    Pure, so the mapping is testable without a database: which resource, which
    action and which ids end up on the row is exactly what the test asserts.
    """
    payload = envelope.get("payload") or {}
    conversation_id = payload.get("conversation_id") or envelope.get("aggregate_id")
    return {
        "tenant_id": _uuid_or_none(envelope.get("tenant_id") or payload.get("tenant_id")),
        "actor_user_id": None,
        "action": "apparel.ai.escalated",
        "resource_type": "ai_conversation",
        "resource_id": str(conversation_id or ""),
        "after": {
            "reason": payload.get("reason"),
            "agent": payload.get("agent"),
            "event_id": envelope.get("event_id"),
            "workspace_id": _id_text(envelope.get("workspace_id") or payload.get("workspace_id")),
        },
    }


def sale_audit(envelope: dict) -> dict:
    """The audit row a completed sale writes."""
    payload = envelope.get("payload") or {}
    sale_id = payload.get("sale_id") or payload.get("order_id") or envelope.get("aggregate_id")
    return {
        "tenant_id": _uuid_or_none(envelope.get("tenant_id") or payload.get("tenant_id")),
        "actor_user_id": _uuid_or_none(payload.get("cashier_user_id")),
        "action": "apparel.sales.sale_completed",
        "resource_type": "sale",
        "resource_id": str(sale_id or ""),
        "after": {
            "total": payload.get("total"),
            "currency": payload.get("currency"),
            "event_id": envelope.get("event_id"),
            "workspace_id": _id_text(envelope.get("workspace_id") or payload.get("workspace_id")),
        },
    }


async def _write(row: dict) -> None:
    async with SessionLocal() as session:
        await write_audit_row(
            session,
            row["tenant_id"],
            row["actor_user_id"],
            row["action"],
            row["resource_type"],
            row["resource_id"],
            after=row["after"],
        )
        await session.commit()


@consumes("apparel.ai.agent_escalated")
async def record_escalation(envelope: dict) -> None:
    await _write(escalation_audit(envelope))


@consumes("apparel.sales.sale_completed")
async def record_sale(envelope: dict) -> None:
    await _write(sale_audit(envelope))


def register() -> tuple[str, ...]:
    """Register the application's consumers. Idempotent: startup may retry."""
    from app.platform.events.routing import consumers_for

    for name in CONSUMED_EVENTS:
        if not consumers_for(name):
            raise RuntimeError(f"{name} is declared consumed but no handler is registered")
    return CONSUMED_EVENTS


__all__ = [
    "CONSUMED_EVENTS",
    "escalation_audit",
    "record_escalation",
    "record_sale",
    "register",
    "sale_audit",
]
