"""Analysis events (spec §12.3) — REAL runtime events, no fake progress.

Emitted through the platform outbox in the same transaction as the analysis
itself, so a crashed worker loses nothing and the dashboard's stream carries
only what actually happened. Event types:

* analysis.started      — the run began (question + outcome placeholder)
* analysis.completed    — the outcome, findings count, evidence hash
* analysis.failed       — the run errored (spec: real failures only)

The payload's first key is always ``event_type`` (workers route on it, the
same convention as message.outbound). UI localization happens on the
frontend — the backend never ships human-readable progress strings.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events.writer import add_outbox_event


async def emit_analysis_event(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    event_type: str,
    analysis_id: uuid.UUID,
    run_id: uuid.UUID | None,
    payload: dict | None = None,
) -> None:
    """Stage one analysis event via the outbox (same transaction)."""
    body = {
        "event_type": event_type,
        "analysis_id": str(analysis_id),
        "run_id": str(run_id) if run_id else None,
    }
    if payload:
        body.update(payload)
    await add_outbox_event(
        session,
        aggregate_type="analysis",
        aggregate_id=analysis_id,
        event_type=event_type,
        tenant_id=tenant_id,
        payload=body,
        aggregate_version=1,
    )
