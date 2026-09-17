"""Outbox writer — the ONLY way domain code stages events.

Called INSIDE the caller's transaction: the outbox_events row is flushed with
the business change, so "state changed" and "event staged" commit atomically
(no dual-write hole). The relay (app.core.events.outbox) drains it later.

The SERVICE NEVER COMMITS — this module only ever flushes.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.platform.models import OutboxEvent


async def add_outbox_event(
    session: AsyncSession,
    *,
    aggregate_type: str,
    aggregate_id: UUID,
    event_type: str,
    tenant_id: UUID,
    payload: dict | None = None,
    meta: dict | None = None,
) -> OutboxEvent:
    """Insert a pending OutboxEvent within the caller's transaction.

    - stream: "{aggregate_type}.events" (the bus topic consumers subscribe to)
    - payload: flat dict, the event_type is always the first key
    - meta: always carries tenant_id (the relay is cross-tenant)
    """
    merged_meta = dict(meta or {})
    merged_meta["tenant_id"] = str(tenant_id)

    event = OutboxEvent(
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        stream=f"{aggregate_type}.events",
        payload={"event_type": event_type, **(payload or {})},
        meta=merged_meta,
        status="pending",
    )
    session.add(event)
    await session.flush()
    return event
