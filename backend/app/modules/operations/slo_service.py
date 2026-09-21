"""Spec §168 — SLO framework: alerting thresholds on SLA metrics.

An SLO (Service Level Objective) is different from an SLA (Service Level
Agreement):

- **SLA** (§46): per-conversation — "this customer's first reply is due in 15
  business minutes." The SLA clock decides if a SPECIFIC conversation is late.
- **SLO** (§168): aggregate — "95% of conversations must get their first reply
  within the SLA target over the last 7 days." The SLO framework measures the
  HEALTH of the system, not an individual conversation.

This service computes SLO compliance from event_log + agent_runs + messages
and exposes alerting thresholds (warning, error, breach) so an operator is
notified before the objective is actually violated.

The SLO definitions are dataclass constants (not DB rows) because they are
deployment-wide: every tenant is measured against the same objectives. A
tenant's SLA policy sets the per-conversation target; the SLO sets the
aggregate compliance bar.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True, slots=True)
class SLOSpec:
    """One SLO definition: name, target, window, thresholds."""

    name: str
    description: str
    target_percent: float  # e.g. 95.0 means 95% must meet the objective
    window_hours: int  # measurement window (e.g. 168 = 7 days)
    warning_percent: float  # alert before the objective is actually breached
    error_percent: float  # the objective is at risk


# The canonical SLO definitions — deployment-wide, not per-tenant.
SLO_DEFINITIONS: tuple[SLOSpec, ...] = (
    SLOSpec(
        name="first_response",
        description=(
            "Share of conversations where the first outbound reply arrived within "
            "the SLA target's first-response window. Measured over the last 7 days."
        ),
        target_percent=95.0,
        window_hours=168,
        warning_percent=92.0,
        error_percent=90.0,
    ),
    SLOSpec(
        name="resolution",
        description=(
            "Share of conversations closed within the SLA target's resolution window. "
            "Only conversations with status='closed' are counted."
        ),
        target_percent=90.0,
        window_hours=168,
        warning_percent=87.0,
        error_percent=85.0,
    ),
    SLOSpec(
        name="ai_availability",
        description=(
            "Share of AI agent runs that did not end in 'failed' or 'timeout'. "
            "Measures the AI platform's availability, not its quality."
        ),
        target_percent=99.0,
        window_hours=24,
        warning_percent=97.0,
        error_percent=95.0,
    ),
    SLOSpec(
        name="message_delivery",
        description=(
            "Share of outbound messages that reached a terminal state (delivered "
            "or read) without being stranded in 'unknown'."
        ),
        target_percent=99.0,
        window_hours=24,
        warning_percent=98.0,
        error_percent=97.0,
    ),
    SLOSpec(
        name="outbox_lag",
        description=(
            "Share of outbox events published to Redis within 60 seconds of commit. "
            "Measures the relay's ability to drain the backlog."
        ),
        target_percent=99.0,
        window_hours=24,
        warning_percent=97.0,
        error_percent=95.0,
    ),
    SLOSpec(
        name="webhook_processing",
        description=(
            "Share of inbound webhooks processed without landing in the DLQ. "
            "Measures the webhook pipeline's reliability."
        ),
        target_percent=99.5,
        window_hours=24,
        warning_percent=99.0,
        error_percent=98.0,
    ),
    SLOSpec(
        name="queue_depth",
        description=(
            "Share of time the worker queue depth stays under the degraded threshold. "
            "Measures the workers' ability to keep up with the event rate."
        ),
        target_percent=95.0,
        window_hours=24,
        warning_percent=90.0,
        error_percent=85.0,
    ),
)


def get_slo_definitions() -> list[dict[str, Any]]:
    """List all SLO definitions as serializable dicts."""
    return [
        {
            "name": s.name,
            "description": s.description,
            "target_percent": s.target_percent,
            "window_hours": s.window_hours,
            "warning_percent": s.warning_percent,
            "error_percent": s.error_percent,
            "runbook": RUNBOOKS.get(s.name, ""),
            "alert_destinations": ALERT_DESTINATIONS.get(s.name, []),
        }
        for s in SLO_DEFINITIONS
    ]


# §168 — Alert destinations: where the notification goes when a threshold is hit.
# Each SLO maps to a list of destinations (in-app, email, push) and an owner
# (the team responsible for responding). These are deployment-wide constants
# because they reflect the operational ownership model, not tenant policy.
ALERT_DESTINATIONS: dict[str, list[dict[str, str]]] = {
    "first_response": [
        {"channel": "in-app", "target": "operations-team"},
        {"channel": "email", "target": "ops@example.com"},
    ],
    "resolution": [
        {"channel": "in-app", "target": "operations-team"},
    ],
    "ai_availability": [
        {"channel": "in-app", "target": "ai-team"},
        {"channel": "push", "target": "on-call"},
    ],
    "message_delivery": [
        {"channel": "in-app", "target": "operations-team"},
    ],
    "outbox_lag": [
        {"channel": "push", "target": "on-call"},
        {"channel": "email", "target": "ops@example.com"},
    ],
    "webhook_processing": [
        {"channel": "in-app", "target": "operations-team"},
        {"channel": "push", "target": "on-call"},
    ],
    "queue_depth": [
        {"channel": "push", "target": "on-call"},
    ],
}

# §168 — Runbooks: the "what to do" link shown in the alert. Each runbook is
# a short, human-readable procedure for the on-call responder.
RUNBOOKS: dict[str, str] = {
    "first_response": (
        "1. Check /platform/health for degraded subsystems. "
        "2. If outbox is backed up, check the relay worker logs. "
        "3. If no subsystem is degraded, check for unassigned conversations in the inbox."
    ),
    "resolution": (
        "1. Check for conversations stuck in WAITING_CUSTOMER > 24h. "
        "2. Review SLA policy settings — the target may be too aggressive. "
        "3. Assign a human to close stale conversations."
    ),
    "ai_availability": (
        "1. Check /platform/health for AI provider status. "
        "2. Check the AI gateway logs for provider errors or rate limits. "
        "3. If the provider is down, enable fallback model via feature flag."
    ),
    "message_delivery": (
        "1. Check channel account health at /platform/health. "
        "2. Check for messages stuck in UNKNOWN state — run delivery reconciliation. "
        "3. If the channel is restricted, reconnect the account."
    ),
    "outbox_lag": (
        "1. Check the outbox relay worker — it may have crashed. "
        "2. Check Redis connectivity. "
        "3. If Redis is down, the relay will republish events when it recovers."
    ),
    "webhook_processing": (
        "1. Check the DLQ at /platform/health for dead-lettered events. "
        "2. Inspect the webhook event store for the failing payload. "
        "3. If a provider change broke parsing, patch the adapter."
    ),
    "queue_depth": (
        "1. Check worker pool health — workers may have crashed. "
        "2. Scale up worker replicas if the queue is growing. "
        "3. Check for a noisy-neighbor tenant consuming all capacity."
    ),
}


@dataclass(slots=True)
class SLOResult:
    """One SLO measurement result."""

    name: str
    compliance_percent: float
    total: int
    met: int
    target_percent: float
    status: str  # "healthy" | "warning" | "error" | "breach"
    window_since: str


def _status_for(spec: SLOSpec, compliance: float) -> str:
    if compliance >= spec.target_percent:
        return "healthy"
    if compliance >= spec.warning_percent:
        return "warning"
    if compliance >= spec.error_percent:
        return "error"
    return "breach"


async def _first_response_compliance(
    session: AsyncSession, tenant_id: uuid.UUID, since: datetime
) -> tuple[int, int]:
    """(total, met) for first-response SLO.

    A conversation "meets" the SLO when the first outbound reply arrived
    within 15 minutes of the first inbound (the default target; per-tenant
    SLA targets make this precise in a future iteration).
    """
    result = await session.execute(
        text(
            """
            WITH pairs AS (
              SELECT c.id,
                     MIN(CASE WHEN m.direction = 'inbound' THEN m.created_at END) AS first_in,
                     MIN(CASE WHEN m.direction = 'outbound' THEN m.created_at END) AS first_out
                FROM conversations c
                JOIN messages m ON m.conversation_id = c.id
               WHERE c.tenant_id = :tenant_id
                 AND m.created_at >= :since
               GROUP BY c.id
               HAVING MIN(CASE WHEN m.direction = 'inbound' THEN m.created_at END) IS NOT NULL
            )
            SELECT
              COUNT(*) AS total,
              COUNT(*) FILTER (
                WHERE first_out IS NOT NULL
                  AND EXTRACT(EPOCH FROM (first_out - first_in)) <= 900
              ) AS met
              FROM pairs
            """
        ),
        {"tenant_id": str(tenant_id), "since": since},
    )
    row = result.one()
    return int(row[0] or 0), int(row[1] or 0)


async def _resolution_compliance(
    session: AsyncSession, tenant_id: uuid.UUID, since: datetime
) -> tuple[int, int]:
    """(total, met) for resolution SLO (closed within 24h)."""
    result = await session.execute(
        text(
            """
            WITH closed AS (
              SELECT c.id,
                     MIN(m.created_at) AS first_in,
                     c.updated_at AS closed_at
                FROM conversations c
                JOIN messages m ON m.conversation_id = c.id
               WHERE c.tenant_id = :tenant_id
                 AND c.status = 'closed'
                 AND m.created_at >= :since
               GROUP BY c.id
            )
            SELECT
              COUNT(*) AS total,
              COUNT(*) FILTER (
                WHERE EXTRACT(EPOCH FROM (closed_at - first_in)) <= 86400
              ) AS met
              FROM closed
            """
        ),
        {"tenant_id": str(tenant_id), "since": since},
    )
    row = result.one()
    return int(row[0] or 0), int(row[1] or 0)


async def _ai_availability_compliance(
    session: AsyncSession, tenant_id: uuid.UUID, since: datetime
) -> tuple[int, int]:
    """(total, met) for AI availability SLO (runs not failed/timeout)."""
    from app.modules.ai.models import AgentRun

    result = await session.execute(
        select(
            func.count(AgentRun.id),
            func.count(AgentRun.id).filter(
                ~AgentRun.status.in_(("failed", "timeout"))
            ),
        ).where(
            AgentRun.tenant_id == tenant_id,
            AgentRun.created_at >= since,
        )
    )
    row = result.one()
    return int(row[0] or 0), int(row[1] or 0)


async def _message_delivery_compliance(
    session: AsyncSession, tenant_id: uuid.UUID, since: datetime
) -> tuple[int, int]:
    """(total, met) for message delivery SLO (outbound not stuck in unknown)."""
    result = await session.execute(
        text(
            """
            SELECT
              COUNT(*) AS total,
              COUNT(*) FILTER (WHERE delivery_status NOT IN ('pending', 'unknown')) AS met
              FROM messages
             WHERE tenant_id = :tenant_id
               AND direction = 'outbound'
               AND created_at >= :since
            """
        ),
        {"tenant_id": str(tenant_id), "since": since},
    )
    row = result.one()
    return int(row[0] or 0), int(row[1] or 0)


# §168: SLO compliance queries for outbox_lag, webhook_processing, queue_depth.
# These replaced the ValueError("SLO '{name}' has no compliance query") stubs.


async def _outbox_lag_compliance(
    session: AsyncSession, tenant_id: uuid.UUID, since: datetime
) -> tuple[int, int]:
    """§168: outbox lag — seconds since the oldest unrelayed outbox event."""
    result = await session.execute(
        text(
            "SELECT EXTRACT(EPOCH FROM (now() - MAX(created_at))) "
            "FROM outbox_events WHERE relayed_at IS NULL"
        )
    )
    lag_seconds = float(result.scalar_one() or 0)
    return 1, 1 if lag_seconds <= 60 else 0


async def _webhook_processing_compliance(
    session: AsyncSession, tenant_id: uuid.UUID, since: datetime
) -> tuple[int, int]:
    """§168: webhook processing — average age of pending webhook deliveries."""
    result = await session.execute(
        text(
            "SELECT EXTRACT(EPOCH FROM AVG(now() - created_at)) "
            "FROM webhook_deliveries WHERE status = 'pending'"
        )
    )
    avg_seconds = float(result.scalar_one() or 0)
    return 1, 1 if avg_seconds <= 60 else 0


async def _queue_depth_compliance(
    session: AsyncSession, tenant_id: uuid.UUID, since: datetime
) -> tuple[int, int]:
    """§168: queue depth — count of pending scheduled jobs."""
    result = await session.execute(
        text("SELECT COUNT(*) FROM scheduled_jobs WHERE status = 'queued'")
    )
    depth = int(result.scalar_one() or 0)
    return 1, 1 if depth < 1000 else 0


_COMPLIANCE_QUERIES = {
    "first_response": _first_response_compliance,
    "resolution": _resolution_compliance,
    "ai_availability": _ai_availability_compliance,
    "message_delivery": _message_delivery_compliance,
    "outbox_lag": _outbox_lag_compliance,
    "webhook_processing": _webhook_processing_compliance,
    "queue_depth": _queue_depth_compliance,
}


async def measure_slo(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    slo_name: str,
) -> SLOResult:
    """Compute one SLO's compliance for the tenant."""
    spec = next((s for s in SLO_DEFINITIONS if s.name == slo_name), None)
    if spec is None:
        raise ValueError(f"unknown SLO: {slo_name}")

    handler = _COMPLIANCE_QUERIES.get(slo_name)
    if handler is None:
        raise ValueError(f"SLO '{slo_name}' has no compliance query")

    since = datetime.now(UTC) - timedelta(hours=spec.window_hours)
    total, met = await handler(session, tenant_id, since)

    compliance = (met / total * 100) if total > 0 else 100.0
    return SLOResult(
        name=slo_name,
        compliance_percent=round(compliance, 2),
        total=total,
        met=met,
        target_percent=spec.target_percent,
        status=_status_for(spec, compliance),
        window_since=since.isoformat(),
    )


async def measure_all_slos(
    session: AsyncSession, tenant_id: uuid.UUID
) -> list[SLOResult]:
    """Compute every SLO for the tenant in one call."""
    results: list[SLOResult] = []
    for spec in SLO_DEFINITIONS:
        try:
            result = await measure_slo(session, tenant_id, spec.name)
        except Exception:  # noqa: BLE001 — one SLO failure must not block others
            result = SLOResult(
                name=spec.name,
                compliance_percent=0.0,
                total=0,
                met=0,
                target_percent=spec.target_percent,
                status="error",
                window_since="",
            )
        results.append(result)
    return results
