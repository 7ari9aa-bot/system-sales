"""Outbox writer — the ONLY way domain code stages events.

Called INSIDE the caller's transaction: the outbox_events row is flushed with
the business change, so "state changed" and "event staged" commit atomically
(no dual-write hole). The relay (app.core.events.outbox) drains it later.

The SERVICE NEVER COMMITS — this module only ever flushes.

The staged message is a real §19 envelope: the row's ``meta`` carries the
envelope routing keys (type / tenant_id / occurred_at / aggregate_type /
aggregate_id / version / lineage), so what the relay publishes is exactly what
``schemas.deserialize()`` rebuilds. Building the envelope here — rather than
hand-merging meta — is what keeps the contract honest: an unregistered event
type fails the mutation instead of silently publishing a non-envelope.
"""

from __future__ import annotations

import json
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events.schemas import build_envelope, serialize
from app.modules.platform.models import OutboxEvent


def _auto_correlation_id() -> str | None:
    """§65: pick up the request-scoped correlation_id when available.

    Returns None outside a request (workers, scheduled jobs). Callers that
    process a domain event should pass the event's correlation_id explicitly;
    this auto-fill covers the HTTP → outbox path so every event staged from
    a request carries the request's correlation_id without boilerplate.
    """
    try:
        from app.core.errors import correlation_id_contextvar

        return correlation_id_contextvar.get()
    except LookupError:
        return None


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
    - payload: flat dict, the event_type is always the first key (workers route
      on it: message_worker / platform_workers / event_log)
    - meta: the §19 envelope routing keys PLUS user meta. Always carries
      tenant_id (the relay is cross-tenant, and the SSE gateway fails CLOSED
      without it). Envelope v2 lineage (correlation_id / causation_id /
      producer / schema_version / aggregate_version) rides inside meta too —
      the outbox_events table columns are frozen, so no migration is needed.
    """
    envelope = build_envelope(
        event_type,
        tenant_id=tenant_id,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        payload=payload or {},
        meta=meta or {},
        correlation_id=correlation_id or _auto_correlation_id(),
        causation_id=causation_id,
        producer=producer,
        schema_version=schema_version,
        aggregate_version=aggregate_version,
    )
    # Serialize to the bus wire layout, then parse back: JSONB columns need
    # JSON-native values (serialize maps UUID/datetime via default=str), and
    # storing the serialized form means the row IS what deserialize() reads.
    fields = serialize(envelope)
    event = OutboxEvent(
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        stream=f"{aggregate_type}.events",
        payload={"event_type": event_type, **json.loads(fields["payload"])},
        meta=json.loads(fields["meta"]),
        status="pending",
    )
    session.add(event)
    await session.flush()
    # Consumer-inbox dedupe key: the OUTBOX row id is stable across relay
    # crash-reclaim re-publishes. (The bus previously generated a fresh uuid
    # per XADD, so a reclaimed event got a new id and dedupe never hit —
    # producing duplicate AI replies / double sends.)
    event.meta = {**event.meta, "outbox_id": str(event.id)}
    return event
