"""Platform monitors — "see it before the customer does" (deep research).

The layered model the major platforms converge on (Sentry Release Health,
Datadog RUM monitors, AWS OPS04-BP03, Dynatrace synthetics):

1. SYNTHETIC PROBES — scripted fetches of the storefront/API on a schedule;
   they catch a broken deploy with ZERO real users.
2. RUM HEALTH — the visitor_events stream this platform already collects;
   error-rate per path, load percentiles, and SILENCE (Datadog's "below 1"
   trick: the tracker stopping is itself an alarm — the site is down or the
   tracker broke, and no one filed a ticket).
3. ALERTS — tripped monitors surfaced on the owner console System tab and
   deduplicated over a cooldown so one bad hour is one alert, not sixty.

Redis carries the EPHEMERAL state (last probe result, trip cooldowns) —
transport, not truth; every durable fact (visitor_events) stays in Postgres.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings

logger = logging.getLogger(__name__)

from app.modules.platform.models import VisitorEvent  # noqa: E402

# Monitors evaluate a short rolling window — long enough to ride out a blip,
# short enough to beat the customer's next page load.
WINDOW_MINUTES = 15
SILENCE_MINUTES = 30
PROBE_TIMEOUT_SECONDS = 8.0
ALERT_COOLDOWN_MINUTES = 60

_PROBE_KEY = "platform:monitors:probe:last"
_TRIP_KEY = "platform:monitors:trip:{fingerprint}"


@dataclass(frozen=True, slots=True)
class Alert:
    severity: str  # critical | warning
    code: str
    detail: str
    fingerprint: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "code": self.code,
            "detail": self.detail,
            "fingerprint": self.fingerprint,
        }


async def _window_stats(session: AsyncSession, minutes: int) -> dict[str, Any]:
    since = datetime.now(UTC) - timedelta(minutes=minutes)
    total = (
        await session.execute(
            select(func.count(VisitorEvent.id)).where(VisitorEvent.created_at >= since)
        )
    ).scalar_one()
    errors = (
        await session.execute(
            select(func.count(VisitorEvent.id)).where(
                VisitorEvent.event_type == "error",
                VisitorEvent.created_at >= since,
            )
        )
    ).scalar_one()
    worst_path = (
        await session.execute(
            select(VisitorEvent.path, func.count(VisitorEvent.id).label("n"))
            .where(
                VisitorEvent.event_type == "error",
                VisitorEvent.created_at >= since,
            )
            .group_by(VisitorEvent.path)
            .order_by(func.count(VisitorEvent.id).desc())
            .limit(1)
        )
    ).first()
    return {
        "since": since,
        "total": int(total or 0),
        "errors": int(errors or 0),
        "worst_path": (worst_path[0], int(worst_path[1])) if worst_path else None,
    }


async def _had_traffic_recently(session: AsyncSession, hours: int) -> bool:
    since = datetime.now(UTC) - timedelta(hours=hours)
    n = (
        await session.execute(
            select(func.count(VisitorEvent.id)).where(VisitorEvent.created_at >= since)
        )
    ).scalar_one()
    return int(n or 0) > 0


async def evaluate_monitors(session: AsyncSession) -> list[Alert]:
    """Evaluate the RUM monitors over the rolling window.

    Monitors (matched to what the major platforms alert on first):
    - ERROR SPIKE: ≥3 errors in the window AND error rate ≥ 10% — one bad
      script flooding errors is noise, a real breakage trips this.
    - SILENCE: zero page_view events for 30 minutes while the site HAD
      traffic in the last 24h — the tracker or the site is down (the
      "below 1" alarm; silence is the outage nobody reports).
    """
    alerts: list[Alert] = []
    stats = await _window_stats(session, WINDOW_MINUTES)

    if stats["total"] > 0:
        rate = stats["errors"] / stats["total"]
        if stats["errors"] >= 3 and rate >= 0.10:
            path = stats["worst_path"][0] if stats["worst_path"] else "/"
            alerts.append(
                Alert(
                    severity="critical",
                    code="visitor_error_spike",
                    detail=(
                        f"{stats['errors']} visitor errors in {WINDOW_MINUTES} min "
                        f"({rate:.0%} of {stats['total']} events) — worst: {path}"
                    ),
                    fingerprint=f"visitor_error_spike:{path}",
                )
            )

    if stats["total"] == 0 and await _had_traffic_recently(session, 24):
        page_views = (
            await session.execute(
                select(func.count(VisitorEvent.id)).where(
                    VisitorEvent.event_type == "page_view",
                    VisitorEvent.created_at
                    >= datetime.now(UTC) - timedelta(minutes=SILENCE_MINUTES),
                )
            )
        ).scalar_one()
        if int(page_views or 0) == 0:
            alerts.append(
                Alert(
                    severity="critical",
                    code="telemetry_silence",
                    detail=(
                        f"no page_view events for {SILENCE_MINUTES} minutes while the "
                        "site had traffic in the last 24h — the site or the tracker "
                        "is down (this alarm fires BECAUSE nobody is reporting it)"
                    ),
                    fingerprint="telemetry_silence",
                )
            )
    return alerts


async def run_probes() -> list[dict[str, Any]]:
    """Fetch the configured probe URLs and record results in Redis.

    Returns the results list for the caller; the LAST result is what the
    System tab reads. A probe that returns non-2xx or times out is a
    customer-impacting breakage already happening on the storefront.
    """
    import json as _json

    from app.core.redis import get_redis

    urls = [
        url.strip() for url in (get_settings().owner_probe_urls or "").split(",") if url.strip()
    ]
    results: list[dict[str, Any]] = []
    if urls:
        async with httpx.AsyncClient(
            timeout=PROBE_TIMEOUT_SECONDS, follow_redirects=True
        ) as client:
            for url in urls:
                started = datetime.now(UTC)
                ok = False
                status: int | None = None
                detail = ""
                try:
                    response = await client.get(url)
                    status = response.status_code
                    ok = 200 <= status < 400
                    if not ok:
                        detail = f"HTTP {status}"
                except Exception as exc:  # noqa: BLE001 — a probe failure IS the finding
                    detail = type(exc).__name__
                results.append(
                    {
                        "url": url,
                        "ok": ok,
                        "status": status,
                        "detail": detail,
                        "ms": int((datetime.now(UTC) - started).total_seconds() * 1000),
                    }
                )
        redis = get_redis()
        if redis is not None:
            # Transport, not truth: a Redis outage must not break the probe
            # run itself — the results return to the caller regardless.
            try:
                await redis.set(
                    _PROBE_KEY,
                    _json.dumps({"at": datetime.now(UTC).isoformat(), "results": results}),
                    ex=2 * 24 * 3600,
                )
            except Exception:  # noqa: BLE001 — cache loss is acceptable
                pass
    return results


async def last_probe_results() -> dict[str, Any] | None:
    import json as _json

    from app.core.redis import get_redis

    redis = get_redis()
    if redis is None:
        return None
    try:
        raw = await redis.get(_PROBE_KEY)
    except Exception:  # noqa: BLE001 — Redis down = no probe data, not an error
        return None
    if not raw:
        return None
    try:
        return _json.loads(raw)
    except Exception:  # noqa: BLE001 — corrupt cache is no cache
        return None


async def trip_if_new(
    redis: Any, alerts: list[Alert], *, cooldown_minutes: int = ALERT_COOLDOWN_MINUTES
) -> list[Alert]:
    """Filter alerts down to FIRST trips within the cooldown window.

    One bad hour must page once, not every five minutes. The fingerprint
    (code + path) is the dedupe key — a NEW path tripping still alerts even
    inside another path's cooldown.
    """
    fresh: list[Alert] = []
    for alert in alerts:
        key = _TRIP_KEY.format(fingerprint=alert.fingerprint)
        was_set = await redis.set(key, "1", nx=True, ex=cooldown_minutes * 60)
        if was_set:
            fresh.append(alert)
    return fresh


async def _operator_emails(session: AsyncSession) -> list[str]:
    """Active platform admins — the operators the alerts page."""
    from app.modules.identity.models import User

    rows = (
        (
            await session.execute(
                select(User.email).where(
                    User.is_platform_admin.is_(True),
                    User.is_active.is_(True),
                )
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


async def notify_operators(session: AsyncSession, alerts: list[Alert]) -> int:
    """Push tripped alerts to the operators' email — best-effort, contained.

    Uses the existing generic transactional send (the receipt adapter): one
    message per alert per operator, delivery-idempotent via a uuid5 of the
    alert fingerprint + the trip hour so a scheduler retry inside the same
    hour cannot double-send even if Resend's own idempotency lapses. ANY
    failure (delivery disabled, Resend down, no operators) is logged and
    swallowed — the monitors job must never die because its own alert could
    not be delivered; the System tab still shows the alert.
    """
    if not alerts:
        return 0
    from datetime import datetime as _dt

    from app.modules.identity.email_delivery import (
        EmailDeliveryError,
        ResendEmailSender,
    )

    settings = get_settings()
    if not settings.auth_email_delivery_configured:
        return 0
    recipients = await _operator_emails(session)
    if not recipients:
        return 0

    sender = ResendEmailSender()
    sent = 0
    hour_bucket = _dt.now(UTC).strftime("%Y%m%d%H")
    for alert in alerts:
        subject = f"[SalesOS monitor] {alert.severity}: {alert.code}"
        text = f"{alert.detail}\n\nFingerprint: {alert.fingerprint}"
        html = (
            "<!doctype html><html><body>"
            f"<h2>Platform monitor: {alert.code}</h2>"
            f"<p><b>{alert.severity}</b> — {alert.detail}</p>"
            f"<p style='color:#666'>fingerprint: {alert.fingerprint}</p>"
            "</body></html>"
        )
        for recipient in recipients:
            idempotency = f"monitor:{alert.fingerprint}:{hour_bucket}:{recipient}"
            delivery_id = uuid.uuid5(uuid.NAMESPACE_URL, idempotency)
            try:
                await sender.send_receipt(
                    delivery_id=delivery_id,
                    recipient=recipient,
                    subject=subject,
                    html=html,
                    text=text,
                )
                sent += 1
            except EmailDeliveryError as exc:
                logger.warning(
                    "platform.monitor_alert_undelivered code=%s to=%s retryable=%s",
                    alert.code,
                    recipient,
                    exc,
                )
            except Exception:  # noqa: BLE001 — alerting must never kill the job
                logger.warning(
                    "platform.monitor_alert_failed code=%s to=%s",
                    alert.code,
                    recipient,
                    exc_info=True,
                )
    return sent
