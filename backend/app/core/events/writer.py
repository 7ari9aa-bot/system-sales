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
    correlation_id: str | None = None,
    causation_id: str | None = None,
    producer: str = "core",
    aggregate_version: int | None = None,
    schema_version: int = 1,
) -> OutboxEvent:
    """Insert a pending OutboxEvent within the caller's transaction.

    - stream: "{aggregate_type}.events" (the bus topic consumers subscribe to)
    - payload: flat dict, the event_type is always the first key
    - meta: always carries tenant_id (the relay is cross-tenant). Envelope v2
      lineage (correlation_id / causation_id / producer / schema_version /
      aggregate_version) rides inside meta too — the outbox_events table
      columns are frozen, so no migration is needed for v2.
    """
    merged_meta = dict(meta or {})
    merged_meta["tenant_id"] = str(tenant_id)
    if correlation_id is not None:
        merged_meta["correlation_id"] = correlation_id
    if causation_id is not None:
        merged_meta["causation_id"] = causation_id
    merged_meta["producer"] = producer
    merged_meta["schema_version"] = schema_version
    if aggregate_version is not None:
        merged_meta["aggregate_version"] = aggregate_version

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
