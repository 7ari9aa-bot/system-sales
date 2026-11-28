"""SLO framework for the Settings Configuration Control Plane.

Defines the service-level objectives the settings system is held to, measures
them against the existing metrics infrastructure (``app.core.metrics`` Redis
counters + Prometheus gauges), and exposes a read endpoint for the admin.

Three SLOs:

1. **settings_effective_latency** — the wall-clock time to resolve
   ``GET /settings/effective``.  Target: p99 under ``500 ms``.  Measured by
   timing the handler and incrementing three counters per request: total
   requests, total duration, and slow-count (requests above the threshold).

2. **notification_delivery** — the fraction of ``NotificationService.dispatch``
   calls that succeed (in-app row created + outbox event staged).  Target:
   ``99 %`` success.  Measured by incrementing a counter with
   ``outcome=delivered|failed``.

3. **outbox_lag** — the age of the oldest unpublished outbox row.  Target:
   under ``30 s``.  Reuses the existing ``outbox_oldest_pending_seconds``
   gauge from ``app.core.metrics``.

The targets are constants, not settings: they are the operations contract and
changing one is a decision, not a configuration knob.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from typing import Any

from app.core.metrics import _read_counter, collect_outbox, increment

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------ targets

#: Latency threshold (seconds) above which a /settings/effective request counts as "slow".
SLO_LATENCY_TARGET_SECONDS: float = 0.5
#: Minimum success rate for notification dispatch (fraction, 0–1).
SLO_NOTIFICATION_SUCCESS_TARGET: float = 0.99
#: Maximum acceptable outbox lag (seconds).
SLO_OUTBOX_LAG_TARGET_SECONDS: float = 30.0

#: Metric names (must match CATALOGUE entries in ``app.core.metrics``).
_M_REQUESTS = "settings_effective_requests_total"
_M_DURATION = "settings_effective_duration_seconds_total"
_M_SLOW = "settings_effective_slow_total"
_M_NOTIF = "notification_delivery_total"

_COLLECTOR = "settings_effective"


# ------------------------------------------------------------------ recording


async def record_settings_resolve(*, duration_seconds: float, redis: Any = None) -> None:
    """Record one ``/settings/effective`` request.

    Increments the request counter, adds the duration to the total, and
    increments the slow counter when the duration exceeds the SLO target.
    All writes are fire-and-forget (``strict=False``): a metrics outage must
    never break a settings read.
    """
    await increment(_M_REQUESTS, value=1, redis=redis, strict=False, collector=_COLLECTOR)
    await increment(
        _M_DURATION,
        value=duration_seconds,
        redis=redis,
        strict=False,
        collector=_COLLECTOR,
    )
    if duration_seconds > SLO_LATENCY_TARGET_SECONDS:
        await increment(_M_SLOW, value=1, redis=redis, strict=False, collector=_COLLECTOR)


async def record_notification_delivery(*, succeeded: bool, redis: Any = None) -> None:
    """Record one notification dispatch outcome."""
    outcome = "delivered" if succeeded else "failed"
    await increment(_M_NOTIF, value=1, redis=redis, strict=False, outcome=outcome)


# ------------------------------------------------------------------ status


@dataclass(frozen=True)
class SLOStatus:
    """The current measurement and compliance verdict for one SLO."""

    name: str
    description: str
    target: str
    status: str  # "healthy" | "degraded" | "unknown"
    measurements: dict[str, Any]


def _metric_def(name: str) -> Any:
    from app.core.metrics import _BY_NAME

    return _BY_NAME[name]


async def _read_single_counter(name: str, *, redis: Any = None) -> float:
    """Return the sole value of a no-label counter, or 0.0 if unreadable."""
    samples = await _read_counter(_metric_def(name), redis)
    if not samples:
        return 0.0
    return float(samples[0].value)


async def get_slo_status(*, redis: Any = None, session_factory: Any = None) -> dict[str, Any]:
    """Read all counters and return the SLO dashboard as a dict.

    The caller (the admin endpoint) serialises this to JSON.  Each SLO has a
    ``status`` field: ``healthy`` when within target, ``degraded`` when the
    target is breached, ``unknown`` when no data has been recorded yet.
    """
    # --- SLO 1: settings effective latency ---
    total_requests = await _read_single_counter(_M_REQUESTS, redis=redis)
    total_duration = await _read_single_counter(_M_DURATION, redis=redis)
    slow_requests = await _read_single_counter(_M_SLOW, redis=redis)
    avg_ms = round((total_duration / total_requests) * 1000, 1) if total_requests else 0.0
    slow_pct = round((slow_requests / total_requests) * 100, 2) if total_requests else 0.0
    if total_requests == 0:
        latency_status = "unknown"
    elif slow_pct <= 1.0:
        latency_status = "healthy"
    else:
        latency_status = "degraded"

    slo_latency = SLOStatus(
        name="settings_effective_latency",
        description="Wall-clock time to resolve GET /settings/effective",
        target=f"p99 < {SLO_LATENCY_TARGET_SECONDS * 1000:.0f} ms",
        status=latency_status,
        measurements={
            "total_requests": int(total_requests),
            "avg_ms": avg_ms,
            "slow_requests": int(slow_requests),
            "slow_pct": slow_pct,
        },
    )

    # --- SLO 2: notification delivery ---
    notif_samples = await _read_counter(_metric_def(_M_NOTIF), redis)
    delivered = 0.0
    failed = 0.0
    for s in notif_samples:
        if s.labels.get("outcome") == "delivered":
            delivered = float(s.value)
        elif s.labels.get("outcome") == "failed":
            failed = float(s.value)
    total_notif = delivered + failed
    success_rate = round((delivered / total_notif) * 100, 2) if total_notif else 0.0
    if total_notif == 0:
        notif_status = "unknown"
    elif success_rate >= SLO_NOTIFICATION_SUCCESS_TARGET * 100:
        notif_status = "healthy"
    else:
        notif_status = "degraded"

    slo_notification = SLOStatus(
        name="notification_delivery",
        description="NotificationService.dispatch success rate",
        target=f">= {SLO_NOTIFICATION_SUCCESS_TARGET * 100:.0f}%",
        status=notif_status,
        measurements={
            "total": int(total_notif),
            "delivered": int(delivered),
            "failed": int(failed),
            "success_rate_pct": success_rate,
        },
    )

    # --- SLO 3: outbox lag (reuses existing gauge) ---
    try:
        outbox_samples = await collect_outbox(session_factory=session_factory)
        oldest = 0.0
        pending = 0
        for s in outbox_samples:
            if s.name == "outbox_oldest_pending_seconds":
                oldest = float(s.value)
            elif s.name == "outbox_pending_total":
                pending = int(s.value)
    except Exception:  # noqa: BLE001 — DB may be unreachable from the SLO reader
        logger.debug("slo.outbox_read_failed", exc_info=True)
        oldest = 0.0
        pending = 0

    if oldest == 0 and pending == 0:
        outbox_status = "unknown"
    elif oldest <= SLO_OUTBOX_LAG_TARGET_SECONDS:
        outbox_status = "healthy"
    else:
        outbox_status = "degraded"

    slo_outbox = SLOStatus(
        name="outbox_lag",
        description="Age of the oldest unpublished outbox row",
        target=f"< {SLO_OUTBOX_LAG_TARGET_SECONDS:.0f} s",
        status=outbox_status,
        measurements={
            "oldest_pending_seconds": round(oldest, 3),
            "pending_total": pending,
        },
    )

    return {
        "slos": [asdict(slo_latency), asdict(slo_notification), asdict(slo_outbox)],
    }
